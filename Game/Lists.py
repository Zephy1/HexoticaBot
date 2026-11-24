import threading
import sqlite3
import asyncio
import bisect
import random
import json
import os

from collections.abc import Iterable
from dataclasses import dataclass
from typing import NoReturn

from Database import PersistentAppData
from Utils import Variables
from Utils import Logger
from Utils import Utils

index: "ListIndex"
retiredIDs: dict[Utils.GuildID, set] = {}
retiredInIndex: dict[Utils.GuildID, int] = {}
reservedImported: dict[Utils.GuildID, set] = {}
reservedVoid: dict[Utils.GuildID, set] = {}
voidPools: dict[Utils.GuildID, list] = {}
EMPTY_RANGE = (0, -1)
scanStartSize = 32

@dataclass(slots=True, eq=False)
class BundlePiece:
    hex: Utils.HexCode
    armor: Utils.ArmorType
    slot: Utils.ArmorSlot
    rarity: float
    name: str
    craft: dict
    voidID: str = ""
    bundleID: Utils.BundleID = ""

@dataclass(slots=True, eq=False)
class DropBundle:
    bundleID: Utils.BundleID
    name: str
    rarity: float
    pieces: list[BundlePiece]
    void: bool
    info: dict

class ListIndex:
    def __init__(
        self,
        sourcePath: str,
        indexPath: str,
    ):
        self.sourcePath = sourcePath
        self.indexPath = indexPath
        self.db: sqlite3.Connection | None = None
        self.dbLock = threading.Lock()
        self.totalBundles = 0
        self.armorTypes: list[Utils.ArmorType] = []

    def Prepare(self) -> bool:
        if not os.path.exists(self.sourcePath):
            raise RuntimeError(f"The item list file is missing: {self.sourcePath}.")
        if os.path.exists(self.indexPath) and self.MetaMatches():
            self.Open()
            return False
        print(f"Building the item list index ({self.sourcePath} -> {self.indexPath})")
        self.Build()
        self.Open()
        return True

    def OpenMeta(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.indexPath, check_same_thread=False)
        db.execute("PRAGMA query_only=ON")
        return db

    def MetaMatches(self) -> bool:
        try:
            db = self.OpenMeta()
        except sqlite3.Error:
            return False
        try:
            meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
            source = os.stat(self.sourcePath)
            return (meta.get("sourceSize") == str(source.st_size)
                    and meta.get("sourceMtime") == str(source.st_mtime))
        except sqlite3.Error:
            return False
        finally:
            db.close()

    def Open(self) -> None:
        self.db = self.OpenMeta()
        self.totalBundles = self.db.execute("SELECT COUNT(*) FROM bundles").fetchone()[0]
        self.armorTypes = [row[0] for row in self.db.execute("SELECT armor FROM armorTypes ORDER BY armor")]

    def Build(self) -> None:
        tempPath = f"{self.indexPath}.tmp"
        if os.path.exists(tempPath):
            os.remove(tempPath)
        os.makedirs(os.path.dirname(self.indexPath), exist_ok=True)
        db = sqlite3.connect(tempPath)
        try:
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
            bundleCount, pieceCount = self.ReadSource(db)
            self.CreateTables(db)
            self.WriteMeta(db, bundleCount)
            db.commit()
        except BaseException:
            db.close()
            if os.path.exists(tempPath):
                os.remove(tempPath)
            raise
        db.close()
        os.replace(tempPath, self.indexPath)
        print(f"Built {self.indexPath}: {bundleCount} bundles, {pieceCount} pieces.")

    def Fail(
        self,
        lineNo: int,
        message: str,
    ) -> NoReturn:
        raise RuntimeError(f"{self.sourcePath}:{lineNo}: {message}")

    def ReadSource(self, db: sqlite3.Connection) -> tuple[int, int]:
        db.execute("""CREATE TABLE staging (
            bundleID TEXT, position INTEGER, bundleName TEXT, bundleRarity REAL, bundleData TEXT,
            hex TEXT, armor TEXT, slot TEXT, rarity REAL, pieceData TEXT
        )""")
        seenIDs: dict[str, int] = {}
        pieceCount = 0
        batch = []

        def flushBatch():
            if batch:
                db.executemany("INSERT INTO staging VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
                batch.clear()

        with open(self.sourcePath, encoding="utf-8") as source:
            for lineNo, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    rows = self.ParseBundle(lineNo, json.loads(line), seenIDs)
                except (ValueError, KeyError, TypeError, AttributeError) as e:
                    self.Fail(lineNo, f"invalid bundle line ({type(e).__name__}: {e}).")
                batch.extend(rows)
                pieceCount += len(rows)
                if pieceCount % 200_000 < len(rows):
                    flushBatch()
                    print(f"  {pieceCount} pieces read...")
        if pieceCount == 0:
            self.Fail(1, "the file contains no bundles.")
        flushBatch()
        return len(seenIDs), pieceCount

    def ParseBundle(
        self,
        lineNo: int,
        bundle: dict,
        seenIDs: dict[str, int],
    ) -> list[tuple]:
        bundleID = bundle["id"]
        if not isinstance(bundleID, str) or not bundleID:
            self.Fail(lineNo, "missing or empty bundle id.")
        if bundleID in seenIDs:
            self.Fail(lineNo, f"duplicate bundle id {bundleID} (first seen on line {seenIDs[bundleID]}).")
        seenIDs[bundleID] = lineNo
        pieces = bundle["pieces"]
        if not 1 <= len(pieces) <= 4:
            self.Fail(lineNo, f"a bundle has {len(pieces)} pieces, expected 1 to 4.")
        armor = bundle["armor"].upper()
        rarity = float(bundle["rarity"])
        info = json.dumps({"mode": bundle["mode"], "rarity": rarity, "calc": bundle["rarity_calc"]})
        rows = []
        for position, piece in enumerate(pieces):
            slot = Utils.ArmorSlot(piece["slot"])
            hexCode = piece["hex"].removeprefix("#").upper()
            if len(hexCode) != 6 or any(c not in "0123456789ABCDEF" for c in hexCode):
                self.Fail(lineNo, f"'{piece['hex']}' is not a valid RRGGBB hex color.")
            craft = json.dumps({"method": piece["method"], "from": piece.get("from"), "recipe": piece["recipe"], "calc": piece["rarity_calc"]})
            rows.append((bundleID, position, f"{armor} set", rarity, info, hexCode, armor, slot, float(piece["rarity"]), craft))
        return rows

    def CreateTables(self, db: sqlite3.Connection) -> None:
        db.execute("""CREATE TABLE bundles (
            bundleNumber INTEGER PRIMARY KEY,
            bundleID TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            rarity REAL NOT NULL,
            size INTEGER NOT NULL,
            data TEXT NOT NULL
        )""")
        db.execute("""INSERT INTO bundles
            SELECT rn - 1, bundleID, bundleName, bundleRarity, size, bundleData FROM (
                SELECT ROW_NUMBER() OVER (ORDER BY bundleRarity, bundleID) AS rn, bundleID, bundleName, bundleRarity, size, bundleData FROM (
                    SELECT bundleID, MIN(bundleName) AS bundleName, MIN(bundleRarity) AS bundleRarity, COUNT(*) AS size, MIN(bundleData) AS bundleData
                    FROM staging GROUP BY bundleID))""")
        db.execute("""CREATE TABLE pieces (
            bundleNumber INTEGER NOT NULL, position INTEGER NOT NULL, hex TEXT NOT NULL, armor TEXT NOT NULL,
            slot TEXT NOT NULL, rarity REAL NOT NULL, name TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (bundleNumber, position)) WITHOUT ROWID""")
        db.execute("""INSERT INTO pieces
            SELECT b.bundleNumber, p.position, p.hex, p.armor, p.slot, p.rarity, p.armor || ' ' || p.slot, p.pieceData
            FROM staging p JOIN bundles b ON b.bundleID = p.bundleID""")
        db.execute("CREATE TABLE armorTypes (armor TEXT PRIMARY KEY)")
        db.execute("INSERT INTO armorTypes SELECT DISTINCT armor FROM pieces ORDER BY armor")
        db.execute("CREATE INDEX pieces_piece ON pieces (hex, armor, slot)")

    def WriteMeta(
        self,
        db: sqlite3.Connection,
        bundleCount: int,
    ) -> None:
        db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID")
        sourceStat = os.stat(self.sourcePath)
        db.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("sourceSize", str(sourceStat.st_size)),
            ("sourceMtime", str(sourceStat.st_mtime)),
            ("totalBundles", str(bundleCount)),
        ])

    def BundlesBetween(self, lo: int, hi: int) -> list:
        with self.dbLock:
            return self.db.execute("SELECT bundleNumber, bundleID, name, rarity, size, data FROM bundles WHERE bundleNumber >= ? AND bundleNumber <= ?", (lo, hi)).fetchall()

    def FindPiece(
        self,
        bundleID: Utils.BundleID,
        slot: str,
    ) -> tuple | None:
        with self.dbLock:
            return self.db.execute(
                "SELECT p.hex, p.armor, p.rarity, p.name, p.data FROM pieces p JOIN bundles b ON b.bundleNumber = p.bundleNumber "
                "WHERE b.bundleID = ? AND p.slot = ?",
                (bundleID, slot)).fetchone()

    def FindPieces(
        self,
        pairs: Iterable[tuple[Utils.BundleID, str]],
    ) -> dict[tuple[Utils.BundleID, str], tuple | None]:
        wanted = set(pairs)
        found: dict[tuple[Utils.BundleID, str], tuple | None] = dict.fromkeys(wanted)
        bundleIDs = list({bundleID for bundleID, _ in wanted})
        with self.dbLock:
            for start in range(0, len(bundleIDs), 500):
                chunk = bundleIDs[start:start + 500]
                for bundleID, slot, *row in self.db.execute(
                    "SELECT b.bundleID, p.slot, p.hex, p.armor, p.rarity, p.name, p.data FROM pieces p JOIN bundles b ON b.bundleNumber = p.bundleNumber "
                    f"WHERE b.bundleID IN ({','.join('?' * len(chunk))})", chunk):
                    if (bundleID, slot) in wanted:
                        found[(bundleID, slot)] = tuple(row)
        return found

    def HexCounts(
        self,
        armor: str | None,
        hexCode: str | None,
        bundleIDs: list[Utils.BundleID] | None = None,
    ) -> list[tuple[str, str, int]]:
        filters, values = [], []
        if armor:
            filters.append("p.armor = ?")
            values.append(armor)
        if hexCode:
            filters.append("p.hex = ?")
            values.append(hexCode)
        counts: dict[tuple[str, str], int] = {}
        chunks = [None] if bundleIDs is None else [bundleIDs[start:start + 500] for start in range(0, len(bundleIDs), 500)]
        with self.dbLock:
            for chunk in chunks:
                where, args, sql = list(filters), list(values), "SELECT p.hex, p.slot, COUNT(*) FROM pieces p"
                if chunk is not None:
                    sql += " JOIN bundles b ON b.bundleNumber = p.bundleNumber"
                    where.append(f"b.bundleID IN ({','.join('?' * len(chunk))})")
                    args += chunk
                if where:
                    sql += " WHERE " + " AND ".join(where)
                for hex_, slot, count in self.db.execute(sql + " GROUP BY p.hex, p.slot", args):
                    counts[(hex_, slot)] = counts.get((hex_, slot), 0) + count
        return [(hex_, slot, count) for (hex_, slot), count in counts.items()]

    def PiecesOf(self, bundleNumber: int) -> list:
        with self.dbLock:
            return self.db.execute("SELECT hex, armor, slot, rarity, name, data FROM pieces WHERE bundleNumber = ? ORDER BY position", (bundleNumber,)).fetchall()

    def CountExistingIDs(self, bundleIDs: Iterable[Utils.BundleID]) -> int:
        bundleIDs = list(bundleIDs)
        found = 0
        with self.dbLock:
            for start in range(0, len(bundleIDs), 500):
                chunk = bundleIDs[start:start + 500]
                found += self.db.execute(f"SELECT COUNT(*) FROM bundles WHERE bundleID IN ({','.join('?' * len(chunk))})", chunk).fetchone()[0]
        return found

    def MissingIDs(
        self,
        bundleIDs: Iterable[Utils.BundleID],
        limit: int,
    ) -> list:
        bundleIDs = list(bundleIDs)
        missing = []
        with self.dbLock:
            for start in range(0, len(bundleIDs), 500):
                chunk = bundleIDs[start:start + 500]
                rows = set(row[0] for row in self.db.execute(f"SELECT bundleID FROM bundles WHERE bundleID IN ({','.join('?' * len(chunk))})", chunk))
                missing.extend(bundleID for bundleID in chunk if bundleID not in rows)
                if len(missing) >= limit:
                    return missing[:limit]
        return missing

    def RarityAt(self, bundleNumber: int) -> float:
        with self.dbLock:
            return self.db.execute("SELECT rarity FROM bundles WHERE bundleNumber = ?", (bundleNumber,)).fetchone()[0]

    def RarityBounds(self, minRarity, maxRarity) -> tuple[int, int] | None:
        lo, hi = 0, self.totalBundles - 1
        if lo > hi:
            return None
        if minRarity is not None:
            a, b = 0, self.totalBundles
            while a < b:
                mid = (a + b) // 2
                if self.RarityAt(mid) >= minRarity:
                    b = mid
                else:
                    a = mid + 1
            lo = a
        if maxRarity is not None:
            a, b = lo, self.totalBundles
            while a < b:
                mid = (a + b) // 2
                if self.RarityAt(mid) > maxRarity:
                    b = mid
                else:
                    a = mid + 1
            hi = a - 1
        return None if lo > hi else (lo, hi)

async def BundleFromRow(row) -> DropBundle:
    pieceRows = await asyncio.to_thread(index.PiecesOf, row[0])
    pieces = [
        BundlePiece(pieceRow[0], pieceRow[1], Utils.ArmorSlot(pieceRow[2]), pieceRow[3], pieceRow[4], json.loads(pieceRow[5]), bundleID=row[1])
        for pieceRow in pieceRows
    ]
    return DropBundle(row[1], row[2].replace("_", " "), row[3], pieces, void=False, info=json.loads(row[5]))

async def Initialize() -> None:
    global index
    os.makedirs(os.path.dirname(Variables.ITEM_LIST_FILE_PATH), exist_ok=True)
    index = ListIndex(Variables.ITEM_LIST_FILE_PATH, Variables.ITEM_LIST_INDEX_FILE_PATH)
    rebuilt = await asyncio.to_thread(index.Prepare)
    LoadServerState()
    if rebuilt:
        await WarnMissingRetired()

def LoadServerState() -> None:
    for key, value in PersistentAppData.persistentAppData.items():
        if key.startswith("retired."):
            _, guildID, bundleID = key.split(".", 2)
            retiredIDs.setdefault(int(guildID), set()).add(bundleID)
        elif key.startswith("void."):
            AddVoidRecord(int(key.split(".", 2)[1]), value)

async def WarnMissingRetired() -> None:
    for guildID, ids in retiredIDs.items():
        found = await asyncio.to_thread(index.CountExistingIDs, ids)
        if found < len(ids):
            examples = await asyncio.to_thread(index.MissingIDs, ids, 5)
            await Logger.LogHeadlessError(f"{len(ids) - found} retired bundle IDs no longer exist: {', '.join(examples)}")

def RetiredSet(guildID: Utils.GuildID) -> set:
    return retiredIDs.get(guildID, set())

def ReservedSet(guildID: Utils.GuildID) -> set:
    return reservedImported.get(guildID, set())

async def RetiredInIndex(guildID: Utils.GuildID) -> int:
    if guildID not in retiredInIndex:
        ids = RetiredSet(guildID)
        retiredInIndex[guildID] = await asyncio.to_thread(index.CountExistingIDs, ids) if ids else 0
    return retiredInIndex[guildID]

async def GetAvailable(guildID: Utils.GuildID) -> int:
    return index.totalBundles - await RetiredInIndex(guildID) - len(ReservedSet(guildID))

def ReserveBundle(guildID: Utils.GuildID, bundle: DropBundle) -> None:
    if bundle.void:
        reservedVoid.setdefault(guildID, set()).update(piece.voidID for piece in bundle.pieces)
    else:
        reservedImported.setdefault(guildID, set()).add(bundle.bundleID)

def ReleaseBundle(guildID: Utils.GuildID, bundle: DropBundle) -> None:
    if bundle.void:
        reservedVoid.get(guildID, set()).difference_update(piece.voidID for piece in bundle.pieces)
    else:
        reservedImported.get(guildID, set()).discard(bundle.bundleID)

def RetireImportedBundle(guildID: Utils.GuildID, bundle: DropBundle) -> None:
    reservedImported.get(guildID, set()).discard(bundle.bundleID)
    retired = retiredIDs.setdefault(guildID, set())
    if bundle.bundleID in retired:
        return
    retired.add(bundle.bundleID)
    if guildID in retiredInIndex:
        retiredInIndex[guildID] += 1

def ConsumeVoidBundle(guildID: Utils.GuildID, bundle: DropBundle) -> None:
    ids = {piece.voidID for piece in bundle.pieces}
    reservedVoid.get(guildID, set()).difference_update(ids)
    pool = voidPools.get(guildID, [])
    pool[:] = [entry for entry in pool if entry[1] not in ids]

def AddVoidRecord(guildID: Utils.GuildID, record: dict, found: dict | None = None) -> None:
    pair = (record["bundleID"], record["slot"])
    row = found[pair] if found is not None and pair in found else index.FindPiece(*pair)
    if row is None:
        return
    hexCode, armor, rarity, name, data = row
    piece = {**record, "hex": hexCode, "armor": armor, "rarity": rarity, "name": name, "craft": json.loads(data)}
    bisect.insort(voidPools.setdefault(guildID, []), (rarity, record["itemID"], piece))

def VoidBounds(guildID: Utils.GuildID, rarityRange) -> tuple[int, int]:
    pool = voidPools.get(guildID, [])
    lo = 0
    if rarityRange[0] is not None:
        lo = bisect.bisect_left(pool, rarityRange[0], key=lambda entry: entry[0])
    hi = len(pool) - 1
    if rarityRange[1] is not None:
        hi = bisect.bisect_right(pool, rarityRange[1], key=lambda entry: entry[0]) - 1
    return lo, hi

def PickVoided(
    guildID: Utils.GuildID,
    count: int,
    rarityRange=None,
) -> DropBundle | None:
    pool = voidPools.get(guildID, [])
    lo, hi = VoidBounds(guildID, rarityRange) if rarityRange is not None else (0, len(pool) - 1)
    reserved = reservedVoid.get(guildID, set())
    free = [entry for entry in pool[lo:hi + 1] if entry[1] not in reserved]
    if not free:
        return None
    pieces = [
        BundlePiece(record["hex"], record["armor"], Utils.ArmorSlot(record["slot"]), record["rarity"], record["name"], record["craft"], itemID, record["bundleID"])
        for _, itemID, record in random.sample(free, min(count, len(free)))
    ]
    bundle = DropBundle("void", "Wiped set" if len(pieces) > 1 else "Wiped piece", round(sum(piece.rarity for piece in pieces), 2), pieces, void=True, info={})
    ReserveBundle(guildID, bundle)
    return bundle

async def PickBundle(
    guildID: Utils.GuildID,
    luck: float,
    rarityRange=None,
) -> DropBundle | None:
    if await GetAvailable(guildID) <= 0:
        return None
    rareRate = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.RARE_ITEM_SKEW) * luck
    p = random.random() ** (1 / rareRate) if rareRate > 0 else 0.0
    bounds = None
    if rarityRange is not None:
        bounds = await asyncio.to_thread(index.RarityBounds, rarityRange[0], rarityRange[1]) or EMPTY_RANGE
    return await PickImported(guildID, p, bounds)

async def PickImported(
    guildID: Utils.GuildID,
    p: float,
    bounds,
) -> DropBundle | None:
    lo, hi = bounds if bounds is not None else (0, index.totalBundles - 1)
    if lo > hi:
        return None
    n = max(lo, min(hi, int(p * index.totalBundles)))
    radius = scanStartSize
    while True:
        a, b = max(lo, n - radius), min(hi, n + radius)
        rows = await asyncio.to_thread(index.BundlesBetween, a, b)
        retired = RetiredSet(guildID)
        reserved = ReservedSet(guildID)
        best, bestDistance = None, None
        for row in rows:
            if row[1] in retired or row[1] in reserved:
                continue
            distance = abs(row[0] - n)
            if bestDistance is None or distance < bestDistance:
                best, bestDistance = row, distance
        if best is not None:
            reservedImported.setdefault(guildID, set()).add(best[1])
            try:
                return await BundleFromRow(best)
            except BaseException:
                reservedImported[guildID].discard(best[1])
                raise
        if a == lo and b == hi:
            return None
        radius *= 2
