import colorsys
import json

from dataclasses import dataclass
from enum import StrEnum
from string import capwords
from types import SimpleNamespace
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

pageColumns = 6
pageRows = 4
pageSize = pageColumns * pageRows
maxArmorOptions = 24
greyscaleSaturation = 0.12

slotOrder = {slot.value: number for number, slot in enumerate(Utils.ArmorSlot)}

class SortMode(StrEnum):
    RARITY_DESC = "rarityDesc"
    RARITY_ASC = "rarityAsc"
    NEWEST = "newest"
    OLDEST = "oldest"
    ARMOR = "armor"
    PIECE = "piece"
    COLOR = "color"

sortLabels: dict[SortMode, Text] = {
    SortMode.RARITY_DESC: Text.SELL_SORT_RARITY_DESC,
    SortMode.RARITY_ASC: Text.SELL_SORT_RARITY_ASC,
    SortMode.NEWEST: Text.SELL_SORT_NEWEST,
    SortMode.OLDEST: Text.SELL_SORT_OLDEST,
    SortMode.ARMOR: Text.SELL_SORT_ARMOR,
    SortMode.PIECE: Text.SELL_SORT_PIECE,
    SortMode.COLOR: Text.SELL_SORT_COLOR,
}

class SellSource(StrEnum):
    PLAYER = "player"
    ADMIN = "admin"

class SellResult(NamedTuple):
    sold: list[Utils.ItemID]
    skipped: list[Utils.ItemID]
    coins: Utils.Coins

@dataclass(frozen=True, slots=True)
class SellItem:
    itemID: Utils.ItemID
    armor: str
    slot: str
    hexCode: Utils.HexCode
    name: str
    rarity: float
    claimedAt: int
    value: Utils.Coins
    showcased: bool
    locked: bool
    special: bool

@dataclass(slots=True)
class SellFilter:
    slot: str | None = None
    armor: str | None = None
    minRarity: float | None = None
    maxRarity: float | None = None

    @property
    def active(self) -> bool:
        return any(value is not None for value in (self.slot, self.armor, self.minRarity, self.maxRarity))

    def Matches(self, item: SellItem) -> bool:
        return (
            (self.slot is None or item.slot == self.slot)
            and (self.armor is None or item.armor == self.armor)
            and (self.minRarity is None or item.rarity >= self.minRarity)
            and (self.maxRarity is None or item.rarity <= self.maxRarity)
        )

    def Clear(self) -> None:
        self.slot = self.armor = self.minRarity = self.maxRarity = None

    def Describe(self) -> list[str]:
        parts = []
        if self.slot is not None:
            parts.append(SlotLabel(self.slot))
        if self.armor is not None:
            parts.append(ArmorLabel(self.armor))
        low, high = self.minRarity, self.maxRarity
        if low is not None and high is not None:
            parts.append(Say(Text.SELL_FILTER_RARITY_RANGE, low=Items.FormatRarity(low), high=Items.FormatRarity(high)))
        elif low is not None:
            parts.append(Say(Text.SELL_FILTER_RARITY_MIN, low=Items.FormatRarity(low)))
        elif high is not None:
            parts.append(Say(Text.SELL_FILTER_RARITY_MAX, high=Items.FormatRarity(high)))
        return parts

def ArmorLabel(armor: str) -> str:
    return capwords(armor.replace("_", " "))

def SlotLabel(slot: str) -> str:
    return slot.title()

def ParseSlot(text: str | None) -> str | None:
    cleaned = (text or "").strip().upper()
    if not cleaned:
        return None
    for slot in Utils.ArmorSlot:
        if slot.value == cleaned or slot.value.startswith(cleaned):
            return slot.value
    return None

async def LoadItems(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    profile: dict,
) -> list[SellItem]:
    scope = Profiles.Scope(guildID, userID)
    rows = await PersistentUserData.Read(scope)
    multiplier = Upgrades.SellMultiplier(profile, guildID)
    showcased = {itemID for itemIDs in profile["showcase"].values() for itemID in itemIDs}
    pending = Trading.PendingItems(guildID)
    threshold = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.SPECIAL_ALERT_THRESHOLD)

    items = []
    for key, row in rows.items():
        if not key.startswith("item."):
            continue
        itemID = key.removeprefix("item.")
        data = json.loads(row)
        rarity = data["rarity"]
        items.append(SellItem(
            itemID=itemID,
            armor=str(data["armor"]),
            slot=str(data["slot"]),
            hexCode=data["hex"],
            name=Items.PieceName(SimpleNamespace(name=data["name"])),
            rarity=rarity,
            claimedAt=data.get("claimedAt", 0),
            value=Drops.SellValue(guildID, rarity, multiplier),
            showcased=itemID in showcased,
            locked=itemID in pending,
            special=rarity >= threshold,
        ))
    return items

def HueKey(item: SellItem) -> tuple:
    red, green, blue = (int(item.hexCode[number:number + 2], 16) / 255 for number in (0, 2, 4))
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    return (saturation < greyscaleSaturation, round(hue, 3), -value, item.itemID)

def SortKey(mode: SortMode, item: SellItem) -> tuple:
    slot = slotOrder.get(item.slot, len(slotOrder))
    match mode:
        case SortMode.RARITY_DESC:
            return (-item.rarity, item.itemID)
        case SortMode.RARITY_ASC:
            return (item.rarity, item.itemID)
        case SortMode.NEWEST:
            return (-item.claimedAt, item.itemID)
        case SortMode.OLDEST:
            return (item.claimedAt, item.itemID)
        case SortMode.ARMOR:
            return (item.armor, slot, -item.rarity, item.itemID)
        case SortMode.PIECE:
            return (slot, item.armor, -item.rarity, item.itemID)
        case SortMode.COLOR:
            return HueKey(item)
    return (item.itemID,)

def Arrange(items: list[SellItem], filters: SellFilter, mode: SortMode) -> list[SellItem]:
    return sorted((item for item in items if filters.Matches(item)), key=lambda item: SortKey(mode, item))

def ArmorCounts(items: list[SellItem]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.armor] = counts.get(item.armor, 0) + 1
    return sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))

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
