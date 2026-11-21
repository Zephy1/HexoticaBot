import colorsys
import json
import re

from dataclasses import dataclass
from types import SimpleNamespace
from string import capwords
from enum import StrEnum

from Database import PersistentUserData
from Utils.Translation import Say, Text
from Game import ColorSearch
from Game import Upgrades
from Game import Profiles
from Game import Trading
from Utils import Utils
from Game import Drops
from Game import Items

pageColumns = 6
pageRows = 4
pageSize = pageColumns * pageRows
maxArmorOptions = 24
greyscaleSaturation = 0.12

slotOrder = {slot.value: number for number, slot in enumerate(Utils.ArmorSlot)}

slotAliases = {
    alias: slot.value
    for slot, aliases in (
        (Utils.ArmorSlot.HELMET, ("helmet", "helm")),
        (Utils.ArmorSlot.CHESTPLATE, ("chestplate", "chest", "cp")),
        (Utils.ArmorSlot.LEGGINGS, ("leggings", "legging", "legs", "leg", "pants", "pant")),
        (Utils.ArmorSlot.BOOTS, ("boots", "boot", "shoes", "shoe")),
    )
    for alias in aliases
}

class SortMode(StrEnum):
    RARITY_DESC = "rarityDesc"
    RARITY_ASC = "rarityAsc"
    NEWEST = "newest"
    OLDEST = "oldest"
    ARMOR = "armor"
    PIECE = "piece"
    COLOR = "color"

sortLabels: dict[SortMode, Text] = {
    SortMode.RARITY_DESC: Text.INVENTORY_SORT_RARITY_DESC,
    SortMode.RARITY_ASC: Text.INVENTORY_SORT_RARITY_ASC,
    SortMode.NEWEST: Text.INVENTORY_SORT_NEWEST,
    SortMode.OLDEST: Text.INVENTORY_SORT_OLDEST,
    SortMode.ARMOR: Text.INVENTORY_SORT_ARMOR,
    SortMode.PIECE: Text.INVENTORY_SORT_PIECE,
    SortMode.COLOR: Text.INVENTORY_SORT_COLOR,
}

@dataclass(frozen=True, slots=True)
class InventoryItem:
    itemID: Utils.ItemID
    armor: str
    slot: str
    hexCode: Utils.HexCode
    name: str
    rarity: float
    claimedAt: int
    value: Utils.Coins
    showcaseSlot: int | None
    locked: bool
    special: bool

    @property
    def showcased(self) -> bool:
        return self.showcaseSlot is not None

@dataclass(slots=True)
class InventoryFilter:
    slot: str | None = None
    armor: str | None = None
    minRarity: float | None = None
    maxRarity: float | None = None
    search: str = ""
    query: ColorSearch.Query | None = None

    @property
    def active(self) -> bool:
        return bool(self.search) or any(value is not None for value in (self.slot, self.armor, self.minRarity, self.maxRarity))

    def SetSearch(self, text: str) -> None:
        self.search = text.strip()
        self.query = ColorSearch.Parse(self.search)

    def Matches(self, item: InventoryItem) -> bool:
        return (
            (self.slot is None or item.slot == self.slot)
            and (self.armor is None or item.armor == self.armor)
            and (self.minRarity is None or item.rarity >= self.minRarity)
            and (self.maxRarity is None or item.rarity <= self.maxRarity)
            and (self.query is None or SearchMatches(self.query, item))
        )

    def Clear(self) -> None:
        self.slot = self.armor = self.minRarity = self.maxRarity = self.query = None
        self.search = ""

    def Describe(self) -> list[str]:
        parts = []
        if self.slot is not None:
            parts.append(SlotLabel(self.slot))
        if self.armor is not None:
            parts.append(ArmorLabel(self.armor))
        low, high = self.minRarity, self.maxRarity
        if low is not None and high is not None:
            parts.append(Say(Text.INVENTORY_FILTER_RARITY_RANGE, low=Items.FormatRarity(low), high=Items.FormatRarity(high)))
        elif low is not None:
            parts.append(Say(Text.INVENTORY_FILTER_RARITY_MIN, low=Items.FormatRarity(low)))
        elif high is not None:
            parts.append(Say(Text.INVENTORY_FILTER_RARITY_MAX, high=Items.FormatRarity(high)))
        if self.search:
            parts.append(Say(Text.INVENTORY_FILTER_SEARCH, text=self.search))
        return parts

def SearchMatches(query: ColorSearch.Query, item: InventoryItem) -> bool:
    if query.colors and ColorSearch.Nearest(query, item.hexCode) > ColorSearch.colorThreshold:
        return False
    text = re.sub(r"[\s_]+", "", f"{item.armor}{item.name}{SlotLabel(item.slot)}".lower())
    return all(word in text or item.slot in (ParseSlot(word), slotAliases.get(word)) for word in query.words)

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
    pending: set[Utils.ItemID] | None = None,
) -> list[InventoryItem]:
    scope = Profiles.Scope(guildID, userID)
    rows = await PersistentUserData.Read(scope)
    multiplier = Upgrades.SellMultiplier(profile, guildID)
    showcaseSlots = {itemID: int(slot) for slot, itemIDs in profile["showcase"].items() for itemID in itemIDs}
    if pending is None:
        pending = Trading.PendingItems(guildID)
    threshold = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.SPECIAL_ALERT_THRESHOLD)

    items = []
    for key, row in rows.items():
        if not key.startswith("item."):
            continue
        itemID = key.removeprefix("item.")
        data = json.loads(row)
        rarity = data["rarity"]
        items.append(InventoryItem(
            itemID=itemID,
            armor=str(data["armor"]),
            slot=str(data["slot"]),
            hexCode=data["hex"],
            name=Items.PieceName(SimpleNamespace(name=data["name"])),
            rarity=rarity,
            claimedAt=data["claimedAt"],
            value=Drops.SellValue(guildID, rarity, multiplier),
            showcaseSlot=showcaseSlots.get(itemID),
            locked=itemID in pending,
            special=rarity >= threshold,
        ))
    return items

def HueKey(item: InventoryItem) -> tuple:
    red, green, blue = (int(item.hexCode[number:number + 2], 16) / 255 for number in (0, 2, 4))
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    return (saturation < greyscaleSaturation, round(hue, 3), -value, item.itemID)

def SortKey(mode: SortMode, item: InventoryItem) -> tuple:
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

def Arrange(items: list[InventoryItem], filters: InventoryFilter, mode: SortMode) -> list[InventoryItem]:
    matched = [item for item in items if filters.Matches(item)]
    query = filters.query
    if query is not None and query.colors:
        return sorted(matched, key=lambda item: (ColorSearch.Nearest(query, item.hexCode), SortKey(mode, item)))
    return sorted(matched, key=lambda item: SortKey(mode, item))

def ArmorCounts(items: list[InventoryItem]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.armor] = counts.get(item.armor, 0) + 1
    return sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))

async def LoadSelected(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    itemIDs: list[Utils.ItemID],
) -> list[InventoryItem]:
    wanted = set(itemIDs)
    if not wanted:
        return []
    profile = Profiles.CachedProfile(Profiles.Scope(guildID, userID))
    items = await LoadItems(guildID, userID, profile, set())
    return Arrange([item for item in items if item.itemID in wanted], InventoryFilter(), SortMode.RARITY_DESC)
