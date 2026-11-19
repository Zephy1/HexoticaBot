import json

from enum import StrEnum
from typing import NamedTuple

from Database import PersistentUserData
from Utils.Translation import Say, Text
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

async def SellItems(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    itemIDs: list[Utils.ItemID],
    source: SellSource = SellSource.PLAYER,
) -> SellResult:
    scope = Profiles.Scope(guildID, userID)
    await Profiles.EnsureProfile(guildID, userID)
    records: list[dict] = []

    def build():
        profile = Profiles.CachedProfile(scope)
        if profile is None:
            raise ValueError(Say(Text.NO_PROFILE_USER))
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
            item = json.loads(row)
            record = Items.VoidRecord(itemID, item)
            records.append(record)
            sold.append(itemID)
            if paid:
                coins += Drops.SellValue(guildID, item["rarity"], multiplier)
            userRows[f"item.{itemID}"] = None
            appUpdates[f"itemOwner.{guildID}.{itemID}"] = None
            appUpdates[f"appData.void.{guildID}.{itemID}"] = record

        if not sold:
            return {}, {}, SellResult([], skipped, 0)

        profile["coins"] += coins
        Profiles.Unshowcase(profile, sold)
        userRows["profile"] = profile
        return {scope: userRows}, appUpdates, SellResult(sold, skipped, coins)

    def onSuccess():
        for record in records:
            Lists.AddVoidRecord(guildID, record)

    return await Atomic.AtomicUpdate(guildID, [scope], build, useCommitLock=False, onSuccess=onSuccess)
