import asyncio
import json

from typing import NamedTuple
from enum import StrEnum

from Database import PersistentUserData
from Database import Atomic
from Game import Upgrades
from Game import Profiles
from Game import Trading
from Game import Drops
from Game import Items
from Game import Lists
from Utils import Utils

class SellSource(StrEnum):
    PLAYER = "player"
    ADMIN = "admin"

class SellResult(NamedTuple):
    sold: list[Utils.ItemID]
    skipped: list[Utils.ItemID]
    coins: Utils.Coins

def ParseSale(snapshot: list[tuple[Utils.ItemID, str]]) -> tuple[dict, dict]:
    parsed = {itemID: (row, json.loads(row)) for itemID, row in snapshot}
    return parsed, Lists.index.FindPieces({(item["bundleID"], item["slot"]) for _, item in parsed.values()})

async def SellItems(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    itemIDs: list[Utils.ItemID],
    source: SellSource = SellSource.PLAYER,
) -> SellResult:
    scope = Profiles.Scope(guildID, userID)
    await Profiles.EnsureProfile(guildID, userID)
    records: list[dict] = []

    owned = PersistentUserData.persistentUserData.get(scope, {})
    snapshot = [(itemID, owned[f"item.{itemID}"]) for itemID in dict.fromkeys(itemIDs) if f"item.{itemID}" in owned]
    parsed, found = await asyncio.to_thread(ParseSale, snapshot)

    def build():
        profile = Profiles.RequiredProfile(guildID, userID)
        multiplier = Upgrades.SellMultiplier(profile, guildID)
        owned = PersistentUserData.persistentUserData.get(scope, {})
        paid = source is SellSource.PLAYER
        pending = Trading.PendingItems(guildID) if paid else set()

        sold: list[Utils.ItemID] = []
        skipped: list[Utils.ItemID] = []
        userRows: dict = {}
        appUpdates: dict = {}
        coins = 0
        for itemID in dict.fromkeys(itemIDs):
            row = owned.get(f"item.{itemID}")
            if row is None or itemID in pending:
                skipped.append(itemID)
                continue
            cached = parsed.get(itemID)
            item = cached[1] if cached is not None and cached[0] == row else json.loads(row)
            record = Items.VoidRecord(itemID, item)
            records.append(record)
            sold.append(itemID)
            if paid:
                coins += Drops.SellValue(guildID, item["rarity"], multiplier)
                Profiles.AddStat(profile, "sold.pieces")
                Profiles.AddStat(profile, f"sold.armor.{item['armor']}")
                Profiles.AddStat(profile, f"sold.slot.{item['slot']}")
            userRows[f"item.{itemID}"] = None
            appUpdates[f"appData.void.{guildID}.{itemID}"] = record

        if not sold:
            return {}, {}, SellResult([], skipped, 0)

        Profiles.Earn(profile, "sales", coins)
        Profiles.Unshowcase(profile, sold)
        userRows["profile"] = profile
        return {scope: userRows}, appUpdates, SellResult(sold, skipped, coins)

    def onSuccess():
        for record in records:
            Lists.AddVoidRecord(guildID, record, found)

    return await Atomic.AtomicUpdate(guildID, [scope], build, useCommitLock=False, onSuccess=onSuccess)
