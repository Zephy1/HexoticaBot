import threading
import datetime
import sqlite3
import asyncio
import glob
import json
import os

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from Utils import Variables
from Utils import Logger

database = None
databaseLock = threading.Lock()
readDatabase = None
readDatabaseLock = threading.Lock()
backupDelaySeconds = 4 * 60 * 60

instanceLockFile = None

def PrefixRange(prefix: str) -> tuple[str, str]:
    return prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1)

def LockSingleInstance() -> None:
    global instanceLockFile
    lockFile = open(f"{Variables.PERSISTENT_DB_FILE_PATH}.lock", "a")
    try:
        if os.name == "nt":
            msvcrt.locking(lockFile.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lockFile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lockFile.close()
        raise RuntimeError("Another bot is already using the database.")
    instanceLockFile = lockFile

async def OpenDatabase() -> None:
    global database, readDatabase
    if database is not None:
        return

    LockSingleInstance()
    db = sqlite3.connect(Variables.PERSISTENT_DB_FILE_PATH, check_same_thread=False, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS data (collection TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (collection, key)) WITHOUT ROWID")

    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        db.close()
        raise RuntimeError(f"{Variables.PERSISTENT_DB_FILE_PATH} is corrupted, load latest backup.")

    readDatabase = sqlite3.connect(Variables.PERSISTENT_DB_FILE_PATH, check_same_thread=False, isolation_level=None)
    readDatabase.execute("PRAGMA query_only=ON")
    database = db

async def LoadCollection(name: str) -> dict:
    with databaseLock:
        rows = database.execute("SELECT key, value FROM data WHERE collection = ?", (name,)).fetchall()
    return {key: json.loads(value) for key, value in rows}

def ReadPrefixBlocking(name: str, prefix: str) -> dict:
    with readDatabaseLock:
        rows = readDatabase.execute("SELECT key, value FROM data WHERE collection = ? AND key >= ? AND key < ?", (name, *PrefixRange(prefix))).fetchall()
    return {key[len(prefix):]: value for key, value in rows}

async def ReadPrefix(name: str, prefix: str) -> dict:
    return await asyncio.to_thread(ReadPrefixBlocking, name, prefix)

def ReadRowBlocking(name: str, key: str) -> str | None:
    with readDatabaseLock:
        row = readDatabase.execute("SELECT value FROM data WHERE collection = ? AND key = ?", (name, key)).fetchone()
    return None if row is None else row[0]

async def ReadRow(name: str, key: str) -> str | None:
    return await asyncio.to_thread(ReadRowBlocking, name, key)

def SearchPrefixBlocking(
    name: str,
    prefix: str,
    text: str,
    limit: int,
    byRarity: bool,
) -> list[tuple[str, str]]:
    query = "SELECT key, value FROM data WHERE collection = ? AND key >= ? AND key < ?"
    values: list = [name, *PrefixRange(prefix)]
    if text:
        query += " AND instr(lower(substr(key, ?)), ?) > 0"
        values += [len(prefix) + 1, text.lower()]
    query += " ORDER BY json_extract(value, '$.rarity') DESC, key DESC LIMIT ?" if byRarity else " ORDER BY key LIMIT ?"
    values.append(limit)
    with readDatabaseLock:
        rows = readDatabase.execute(query, values).fetchall()
    return [(key[len(prefix):], value) for key, value in rows]

async def SearchPrefix(
    name: str,
    prefix: str,
    text: str,
    limit: int,
    byRarity: bool = False,
) -> list[tuple[str, str]]:
    return await asyncio.to_thread(SearchPrefixBlocking, name, prefix, text, limit, byRarity)

def ItemSupplyBlocking(prefix: str, armor: str | None, hexCode: str | None, rows: bool = False) -> list[tuple]:
    columns = "substr(key, instr(key, ':item.') + 6), value" if rows else "json_extract(value, '$.hex'), json_extract(value, '$.slot'), COUNT(*)"
    query = f"SELECT substr(key, ?, instr(key, ':item.') - ?), {columns} FROM data WHERE collection = 'userData' AND key >= ? AND key < ? AND instr(key, ':item.') > 0 AND json_extract(value, '$.bundleID') IS NOT 'admin'"
    values: list = [len(prefix) + 1, len(prefix) + 1, *PrefixRange(prefix)]
    if armor is not None:
        query += " AND json_extract(value, '$.armor') = ?"
        values.append(armor)
    if hexCode is not None:
        query += " AND json_extract(value, '$.hex') = ?"
        values.append(hexCode)
    with readDatabaseLock:
        return readDatabase.execute(query + ("" if rows else " GROUP BY 1, 2, 3"), values).fetchall()

async def ItemSupply(prefix: str, armor: str | None, hexCode: str | None = None, rows: bool = False) -> list[tuple]:
    return await asyncio.to_thread(ItemSupplyBlocking, prefix, armor, hexCode, rows)

async def WriteRows(rows: list[tuple[str, str, str | None]]) -> None:
    if rows:
        await asyncio.to_thread(WriteRowsBlocking, rows)

def WriteRowsBlocking(rows: list[tuple[str, str, str | None]]) -> None:
    with databaseLock:
        database.execute("BEGIN IMMEDIATE")
        try:
            for name, key, serialized in rows:
                if serialized is None:
                    database.execute("DELETE FROM data WHERE collection = ? AND key = ?", (name, key))
                else:
                    database.execute("INSERT OR REPLACE INTO data VALUES (?, ?, ?)", (name, key, serialized))
            database.execute("COMMIT")
        except BaseException:
            if database.in_transaction:
                database.execute("ROLLBACK")
            raise

def BackupDatabase(keep: int = 12, backupPath: str | None = None) -> None:
    backupPrefix = os.path.join(Variables.PERSISTENT_DATA_BACKUPS_PATH, "Persistent")
    scheduled = backupPath is None
    if scheduled:
        backupPath = f"{backupPrefix}_{datetime.datetime.now().strftime('%Y%m%d%H')}.db.backup"
    if os.path.exists(backupPath):
        return

    tempPath = f"{backupPath}.tmp"
    source = sqlite3.connect(Variables.PERSISTENT_DB_FILE_PATH)
    destination = sqlite3.connect(tempPath)
    try:
        source.backup(destination)
        if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("New backup failed its integrity check, kept the older backups.")
    except BaseException:
        destination.close()
        if os.path.exists(tempPath):
            os.remove(tempPath)
        raise
    finally:
        source.close()
    destination.close()
    os.replace(tempPath, backupPath)
    if scheduled:
        for oldPath in sorted(glob.glob(glob.escape(backupPrefix) + "_*.db.backup"))[:-keep]:
            os.remove(oldPath)

async def BackupLoop():
    while True:
        try:
            await asyncio.to_thread(BackupDatabase)
        except Exception as e:
            await Logger.LogHeadlessError(f"Error in BackupLoop: {e}")
        await asyncio.sleep(backupDelaySeconds)
