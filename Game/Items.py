import discord
import asyncio
import json
import time

from dataclasses import dataclass
from discord import app_commands

from Database import PersistentUserData
from Utils.Translation import Say, Text
from Database import PersistentAppData
from Database import PersistentData
from Database import Atomic
from Game import Profiles
from Utils import Utils
from Game import Lists

def FormatRarity(rarity: float) -> str:
    return f"{rarity:g}"

def RarityMath(calc: dict) -> str:
    base = calc["count"] if "count" in calc else calc["baseRarity"]
    mods = "".join(
        Say(Text.RARITY_MOD, sign="+" if value >= 0 else "-", value=abs(value), label=key.split(':', 1)[-1].replace(':', ' '))
        for key, value in calc.get("mods", {}).items()
    )
    return Say(Text.RARITY_MATH, base=base, mods=mods) if mods else f"{base:g}"

def CraftText(craft: dict) -> str:
    if not craft:
        return ""
    source = Say(Text.CRAFT_FROM, source=craft['from']) if craft.get("from") else ""
    return Say(Text.CRAFT_TEXT, method=craft['method'], source=source, recipe=craft['recipe'], calc=RarityMath(craft['calc']))

def SetText(info: dict) -> str:
    return Say(Text.SET_TEXT, mode=info['mode'], calc=RarityMath(info['calc'])) if info else ""

def ItemType(armorType: Utils.ArmorType, armorSlot: Utils.ArmorSlot) -> Utils.ItemType:
    return f"{armorType}_{armorSlot}"

def FormatItemID(
    armorType: Utils.ArmorType,
    armorSlot: Utils.ArmorSlot,
    hexCode: Utils.HexCode,
    index: Utils.ItemIndex,
) -> Utils.ItemID:
    return f"{ItemType(armorType, armorSlot)}_{hexCode}_{index}"

@dataclass(frozen=True, slots=True)
class ParsedItemID:
    armorType: Utils.ArmorType
    armorSlot: Utils.ArmorSlot
    hexCode: Utils.HexCode
    index: Utils.ItemIndex

    @property
    def itemID(self) -> Utils.ItemID:
        return FormatItemID(self.armorType, self.armorSlot, self.hexCode, self.index)

def ParseItemID(text: str | None) -> ParsedItemID | None:
    if not text:
        return None
    parts = text.strip().upper().rsplit("_", 3)
    if len(parts) != 4:
        return None
    armorText, slotText, hexCode, indexText = parts
    try:
        armorType = Utils.ArmorType(armorText)
        armorSlot = Utils.ArmorSlot(slotText)
    except ValueError:
        return None
    color = Utils.TryGetHexColor(hexCode)
    if color is None or color.hexCode != hexCode.removeprefix("#"):
        return None
    if not indexText.isdecimal() or int(indexText) < 1:
        return None
    return ParsedItemID(armorType, armorSlot, color.hexCode, int(indexText))

def CounterKey(
    guildID: Utils.GuildID,
    itemType: Utils.ItemType,
    hexCode: Utils.HexCode,
) -> str:
    return f"itemCounter.{guildID}.{itemType}.{hexCode}"

def AllocateWorking(guildID: Utils.GuildID, pieces: list[Lists.BundlePiece]):
    working: dict[tuple[Utils.ItemType, Utils.HexCode], int] = {}
    allocated = []
    for piece in pieces:
        itemType = ItemType(piece.armor, piece.slot)
        index = working.get((itemType, piece.hex)) or PersistentAppData.GetData(CounterKey(guildID, itemType, piece.hex), 1)
        working[(itemType, piece.hex)] = index + 1
        allocated.append((itemType, piece.hex, index, FormatItemID(piece.armor, piece.slot, piece.hex, index)))
    return allocated, working

def CounterUpdates(
    guildID: Utils.GuildID,
    working: dict[tuple[Utils.ItemType, Utils.HexCode], int],
) -> dict[str, int]:
    return {CounterKey(guildID, itemType, hexCode): nextIndex for (itemType, hexCode), nextIndex in working.items()}

def ItemRow(
    piece: Lists.BundlePiece,
    bundle: Lists.DropBundle,
) -> dict:
    return {
        "armor": piece.armor,
        "slot": piece.slot,
        "hex": piece.hex,
        "name": piece.name,
        "rarity": piece.rarity,
        "craft": piece.craft,
        "set": bundle.info,
        "bundleID": bundle.bundleID,
        "bundleName": bundle.name,
        "claimedAt": int(time.time()),
    }

def AddItems(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    sources: list[tuple[Lists.BundlePiece, Lists.DropBundle]],
) -> tuple[dict, dict, list[Utils.ItemID]]:
    allocated, working = AllocateWorking(guildID, [piece for piece, _ in sources])
    itemIDs = [entry[3] for entry in allocated]
    userItems = {f"item.{itemID}": ItemRow(piece, bundle) for itemID, (piece, bundle) in zip(itemIDs, sources)}
    appUpdates = {f"itemOwner.{guildID}.{itemID}": userID for itemID in itemIDs}
    appUpdates.update((f"appData.{key}", value) for key, value in CounterUpdates(guildID, working).items())
    return userItems, appUpdates, itemIDs

async def GiveItem(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    piece: Lists.BundlePiece,
    bundle: Lists.DropBundle,
) -> Utils.ItemID:
    def build():
        userItems, appUpdates, itemIDs = AddItems(guildID, userID, [(piece, bundle)])
        return {Profiles.Scope(guildID, userID): userItems}, appUpdates, itemIDs[0]

    return await Atomic.AtomicUpdate(guildID, [Profiles.Scope(guildID, userID)], build)

def CachedItemRow(scope: Utils.UserScope, itemID: Utils.ItemID) -> dict | None:
    row = PersistentUserData.persistentUserData.get(scope, {}).get(f"item.{itemID}")
    return json.loads(row) if row is not None else None

async def ReadOne(collection: str, key: str):
    value = await PersistentData.ReadRow(collection, key)
    return None if value is None else json.loads(value)

async def GetItemRow(scope: Utils.UserScope, itemID: Utils.ItemID) -> dict | None:
    return await ReadOne("userData", f"{scope}:item.{itemID}")

async def GetItemOwner(
    guildID: Utils.GuildID,
    itemID: Utils.ItemID,
) -> Utils.MemberID | None:
    return await ReadOne("itemOwner", f"{guildID}.{itemID}")

async def RemoveItem(
    guildID: Utils.GuildID,
    ownerID: Utils.MemberID,
    itemID: Utils.ItemID,
    sellValue: int = 0,
) -> dict | None:
    scope = Profiles.Scope(guildID, ownerID)
    item = await GetItemRow(scope, itemID)
    if item is None:
        return None
    record = {
        "itemID": itemID,
        "hex": item["hex"],
        "armor": item["armor"],
        "slot": item["slot"],
        "name": item["name"],
        "rarity": item["rarity"],
        "craft": item.get("craft"),
    }

    def build():
        profile = Profiles.CachedProfile(scope)
        if profile is None or f"item.{itemID}" not in PersistentUserData.persistentUserData.get(scope, {}):
            raise ValueError(Say(Text.ITEM_NOT_OWNED, itemID=itemID, ownerID=ownerID))
        profile["coins"] += sellValue
        Profiles.Unshowcase(profile, [itemID])
        userUpdates = {
            scope: {
                "profile": profile,
                f"item.{itemID}": None,
            }
        }
        appUpdates = {
            f"itemOwner.{guildID}.{itemID}": None,
            f"appData.void.{guildID}.{itemID}": record,
        }
        return userUpdates, appUpdates, record

    def onSuccess():
        Lists.AddVoidRecord(guildID, record)
    return await Atomic.AtomicUpdate(guildID, [scope], build, useCommitLock=False, onSuccess=onSuccess)

async def AutocompleteUserItems(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice]:
    userID = getattr(getattr(interaction.namespace, "user", None), "id", None)
    if not await Utils.IsValidMember(interaction.guild_id, userID):
        return []
    return await _AutocompleteUserItems(interaction, current, userID)
async def _AutocompleteUserItems(
    interaction: discord.Interaction,
    current: str,
    ownerID: Utils.MemberID | None = None,
) -> list[app_commands.Choice]:
    guildID = interaction.guild_id
    if guildID is None:
        return []
    scope = Profiles.Scope(guildID, ownerID or interaction.user.id)
    current = current.lower().replace("#", "")
    rows = await PersistentData.SearchPrefix("userData", f"{scope}:item.", current, 25, byRarity=True)
    return [
        app_commands.Choice(name=Say(Text.AUTOCOMPLETE_ITEM, itemID=itemID, rarity=FormatRarity(json.loads(row)['rarity']))[:100], value=itemID)
        for itemID, row in rows
    ]

async def AutocompleteGuildItems(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice]:
    current = current.lower().replace("#", "")
    rows = await PersistentData.SearchPrefix("itemOwner", f"{interaction.guild_id}.", current, 25)
    return [app_commands.Choice(name=itemID[:100], value=itemID) for itemID, _ in rows]

async def AutocompleteArmorTypes(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice]:
    current = current.lower()
    matches = [armorType for armorType in Lists.index.armorTypes if current in armorType.lower()]
    return [app_commands.Choice(name=armorType, value=armorType) for armorType in matches[:25]]

def GetArmorType(armorText: str) -> Utils.ArmorType | None:
    try:
        return Utils.ArmorType(armorText.strip().upper().replace(" ", "_"))
    except ValueError:
        return None

def ArmorSlots(armorType: Utils.ArmorType | None) -> list[Utils.ArmorSlot]:
    armorSet = None if armorType is None else Utils.ARMOR_SETS.get(armorType)
    return list(Utils.ArmorSlot if armorSet is None else armorSet.pieces)

async def AutocompleteArmorSlots(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice]:
    armorType = GetArmorType(str(getattr(interaction.namespace, "armor_type", "")))
    current = current.lower()
    return [app_commands.Choice(name=slot.title(), value=slot.value) for slot in ArmorSlots(armorType) if current in slot.lower()]

async def PieceSupply(
    guildID: Utils.GuildID,
    itemType: Utils.ItemType,
    hexCode: Utils.HexCode,
) -> dict:
    armorText, _, slot = itemType.rpartition("_")
    supply = {
        "inList": 0,
        "claimed": 0,
        "available": 0,
        "voided": 0,
        "reserved": 0,
        "owned": 0,
        "sold": 0,
    }
    try:
        armorType = Utils.ArmorType(armorText)
    except ValueError:
        return supply

    counts = await asyncio.to_thread(Lists.index.PieceBundleCounts, hexCode, armorType, slot)
    retired = Lists.RetiredSet(guildID)
    reserved = Lists.ReservedSet(guildID)
    for bundleID, copies in counts.items():
        supply["inList"] += copies
        if bundleID in retired:
            supply["claimed"] += copies
        elif bundleID in reserved:
            supply["reserved"] += copies
        else:
            supply["available"] += copies
    reservedVoid = Lists.reservedVoid.get(guildID, ())
    for _, voidID, record in Lists.voidPools.get(guildID, []):
        if record["armor"] == armorType and record["slot"] == slot and record["hex"] == hexCode:
            if voidID in reservedVoid:
                supply["reserved"] += 1
            else:
                supply["voided"] += 1
    ownedRows = await PersistentData.ReadPrefix("itemOwner", f"{guildID}.{itemType}_{hexCode}_")
    supply["owned"] = len(ownedRows)
    issued = PersistentAppData.GetData(CounterKey(guildID, itemType, hexCode), 1) - 1
    supply["sold"] = max(0, issued - supply["owned"])
    return supply
