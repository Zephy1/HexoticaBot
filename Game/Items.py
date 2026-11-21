import discord
import random
import json
import time
import re

from dataclasses import dataclass
from discord import app_commands
from typing import NamedTuple
from string import capwords

from Database import PersistentUserData
from Utils.Translation import Say, Text
from Database import PersistentAppData
from Database import PersistentData
from Database import Atomic
from Game import Profiles
from Utils import Utils
from Game import Lists

dyeEmotes = {
    "RED": "<:PureRed:1499006058172252160>",
    "ORANGE": "<:PureOrange:1499006057568010351>",
    "YELLOW": "<:PureYellow:1499006056670691358>",
    "LIME": "<:PureLime:1499006433654739108>",
    "DARKGREEN": "<:PureDarkGreen:1499006054665682995>",
    "CYAN": "<:PureCyan:1499004857326243925>",
    "LIGHTBLUE": "<:PureLightBlue:1499004829719330907>",
    "DARKBLUE": "<:PureDarkBlue:1499408486776307846>",
    "PURPLE": "<:PurePurple:1499004801609109506>",
    "MAGENTA": "<:PureMagenta:1499004773683429436>",
    "PINK": "<:PurePink:1499004746961387604>",
    "BROWN": "<:PureBrown:1499004717018124329>",
    "WHITE": "<:PureWhite:1499003648997330955>",
    "LIGHTGRAY": "<:PureLightGray:1499004689226661920>",
    "DARKGRAY": "<:PureDarkGray:1499004644175909016>",
    "BLACK": "<:PureBlack:1499003683248017479>",
    "MINT": "<:TrueMint:1499003890559877232>",
    "MAROON": "<:TrueMaroon:1499003856779219016>",
    "NAVY": "<:TrueNavy:1499003811019362456>",
    "ICE": "<:TrueIce:1499003786532753438>",
    "GOLD": "<:TrueGold:1499003748746264659>",
    "NINT": "<:TrueNint:1499003718475972670>",
    "PISTACHIO": "<:TruePistachio:1499003565732134993>",
    "BRICK": "<:TrueBrick:1499006058646212698>",
    "DARKCYAN": "<:TrueDarkCyan:1499006436779495464>",
    "GRAPE": "<:TrueGrape:1499006057018691624>",
    "JADE": "<:TrueJade:1499006059724013658>",
    "STONE": "<:TrueStone:1499006060206358578>",
    "TEAL": "<:TrueTeal:1560156271804416040>",
}

class LootItem(NamedTuple):
    name: str
    price: int
    image: str
    cap: int = 128

class LootLine(NamedTuple):
    name: str
    count: int
    coins: int
    image: str

lootTable = [LootItem(*row) for row in (
    # Armor
    ("Shadow Assassin Set", 35_000_000, "ShadowAssassinHelmet.webp", 1),
    ("Necron's Set", 100_000_000, "NecronHelmet.webp", 1),
    ("Storm's Set", 80_000_000, "StormHelmet.webp", 1),
    ("Goldor's Set", 60_000_000, "GoldorHelmet.webp", 1),
    ("Maxor's Set", 55_000_000, "MaxorHelmet.webp", 1),
    ("Adaptive Set", 12_500_000, "AdaptiveHelmet.webp", 1),
    ("Superior Dragon Set", 45_000_000, "SuperiorHelmet.webp", 1),
    ("Strong Dragon Set", 8_000_000, "StrongHelmet.webp", 1),
    ("Wise Dragon Set", 20_000_000, "WiseHelmet.webp", 1),
    ("Unstable Dragon Set", 7_500_000, "UnstableHelmet.webp", 1),
    ("Young Dragon Set", 9_500_000, "YoungHelmet.webp", 1),
    ("Old Dragon Set", 3_000_000, "OldHelmet.webp", 1),
    ("Protector Dragon Set", 4_000_000, "ProtectorHelmet.webp", 1),
    ("Holy Dragon Set", 5_000_000, "HolyHelmet.webp", 1),
    ("Crown of Greed", 1_000_000, "GoldHelmet_Version=New.webp", 1),
    ("Bonzo's Mask", 2_000_000, "BonzoMask.webp", 1),
    ("Spirit Mask", 30_000_000, "SpiritMask.webp", 1),

    # Weapons
    ("Livid Dagger", 7_000_000, "LividDagger.png"),
    ("Shadow Fury", 30_000_000, "ShadowFury.png"),
    ("Giant's Sword", 110_000_000, "GiantsSword.png"),
    ("Aspect of the Dragons", 2_500_000, "AspectoftheDragons.png"),
    ("Midas' Sword", 50_000_000, "MidasSword.png", 1),
    ("Midas' Staff", 150_000_000, "MidasStaff.png", 1),
    ("Juju Shortbow", 40_000_000, "JujuShortbow.png", 1),
    ("Terminator", 600_000_000, "Terminator.png", 1),
    ("Bonemerang", 25_000_000, "Bonemerang.png", 1),
    ("Spirit Sceptre", 12_000_000, "SpiritSceptre.png", 1),
    ("Flower of Truth", 6_000_000, "FlowerOfTruth.png", 1),
    ("Reaper Falchion", 4_000_000, "ReaperFalchion.png", 1),
    ("Frozen Scythe", 3_000_000, "FrozenScythe.png", 1),
    ("Yeti Sword", 65_000_000, "YetiSword.png", 1),
    ("Pigman Sword", 15_000_000, "PigmanSword.png", 1),
    ("Mosquito Bow", 15_000_000, "MosquitoBow.png", 1),
    ("Runaan's Bow", 2_000_000, "RunaansBow.png", 1),
    ("Spirit Bow", 7_000_000, "SpiritBow.png", 1),
    ("Ember Rod", 13_000_000, "EmberRod.png"),
    ("Bonzo's Staff", 3_000_000, "BonzosStaff.png"),
    ("Wither Cloak Sword", 6_000_000, "WitherCloakSword.png"),

    # Tools
    ("Treecapitator", 2_500_000, "Treecapitator.png", 1),
    ("Gemstone Gauntlet", 30_000_000, "GemstoneGauntlet.png", 1),
    ("Titanium Drill DR-X355", 70_000_000, "TitaniumDrillDRX355.png", 1),

    # Other
    ("Stonk of Stonks", 1_200_000, "Paper.png"),
    ("Enchanted Diamond Block", 200_000, "DiamondBlock.png"),
    ("Necron's Handle", 400_000_000, "Stick.png", 1),
    ("Recombobulator 3000", 12_000_000, "Recombobulator3000.png", 10),
    ("Hot Potato Book", 150_000, "Book.png", 20),
    ("Fuming Potato Book", 2_000_000, "WrittenBook.png", 10),
    ("Overflux Power Orb", 40_000_000, "OverfluxPowerOrb.png", 1),
    ("Scarf's Grimoire", 12_000_000, "ScarfsGrimoire.png", 1),
    ("Zombie Artifact", 9_000_000, "ZombieArtifact.png", 1),
    ("Spider Artifact", 7_000_000, "SpiderArtifact.png", 1),
    ("Treasure Artifact", 100_000_000, "TreasureArtifact.png", 1),
    ("Wither Artifact", 80_000_000, "WitherArtifact.png", 1),
    ("Ender Artifact", 165_000_000, "EnderArtifact.png", 1),
)]
maxLootLines = 8
lootTopLines = 3
lootTopShare = 0.8
lootCoinShare = (0.1, 0.3)
lootJackpotMin = 0.7
lootJackpotChance = 0.5
lootCoinsOnlyChance = 0.4
lootFloor = min(item.price for item in lootTable)

def FormatRarity(rarity: float) -> str:
    return f"{rarity:g}"

def PieceName(piece) -> str:
    words = capwords(piece.name.replace("_", " ")).split()
    if len(words) > 1 and words[-2] in (words[-1], "Pants"):
        words = words[:-1]
    return " ".join(words)

def DyeEmote(name: str) -> str:
    key = re.sub(r"^(PURE|TRUE)", "", re.sub(r"[^A-Z]", "", name.upper()))
    return dyeEmotes.get(key) or capwords(name.replace("_", " "))

def ParseCrafts(text: str) -> list[list[tuple[int, str]]]:
    return [
        [(int(count), name) for count, name in re.findall(r"(\d+)\s+([A-Za-z_ ]+?)\s*(?:,|$)", craft)]
        for craft in text.split(">")
    ]

def DyeList(craft: list[tuple[int, str]]) -> str:
    return " ".join(Say(Text.ROLL_DYE, count=count, dye=DyeEmote(name)) for count, name in craft)

def IsMultiDye(craft: list[tuple[int, str]]) -> bool:
    return sum(count for count, _ in craft) >= 2

def AdvancedDyeText(crafts: list[list[tuple[int, str]]]) -> str:
    steps = [craft for craft in crafts if IsMultiDye(craft)]
    if len(steps) > 1:
        numbered = " ".join(Say(Text.ROLL_DYE_ADVANCED_STEP, number=number, dyes=DyeList(craft)) for number, craft in enumerate(steps, 1))
        return Say(Text.ROLL_DYE_ADVANCED_STEPS, steps=numbered)
    return " ".join(
        Say(Text.ROLL_DYE_ADVANCED, dyes=DyeList(craft)) if IsMultiDye(craft) else DyeList(craft)
        for craft in crafts if craft
    )

def DyeText(recipe: str) -> str:
    fields = [field.strip() for field in recipe.split("|")]
    if len(fields) < 4:
        return ""
    mode, base, method = fields[:3]
    crafts = ParseCrafts(fields[-1])
    if mode in ("advanced", "pure_plus") or method.lower() == "advanced":
        added = AdvancedDyeText(crafts)
    else:
        totals: dict[str, int] = {}
        for craft in crafts:
            for count, name in craft:
                totals[name] = totals.get(name, 0) + count
        added = DyeList([(count, name) for name, count in totals.items()])
    return f"{DyeEmote(base)} {added}" if added and mode == "pure_plus" else added

def CoinsLine(amount: int) -> LootLine:
    return LootLine("Coins", 1, amount, "Coins.png")

def LootPick(item: LootItem, budget: int) -> LootLine:
    count = min(item.cap, budget // item.price)
    return LootLine(item.name, count, count * item.price, item.image)

def RollLoot(coins: int) -> list[LootLine]:
    if random.random() < lootCoinsOnlyChance:
        return [CoinsLine(coins)] if coins > 0 else []

    table = sorted(lootTable, key=lambda item: item.price, reverse=True)
    loot: list[LootLine] = []
    used: set[str] = set()
    left = coins

    def take(item: LootItem, budget: int) -> None:
        nonlocal left
        line = LootPick(item, budget)
        loot.append(line)
        used.add(line.name)
        left -= line.coins

    jackpots = [item for item in table if coins * lootJackpotMin <= item.price <= coins]
    if jackpots and random.random() < lootJackpotChance:
        take(random.choice(jackpots), coins)
    else:
        left -= int(coins * random.uniform(*lootCoinShare))
        for _ in range(lootTopLines):
            share = int(left * lootTopShare)
            item = next((item for item in table if item.name not in used and item.price <= share), None)
            if item is None:
                break
            take(item, share)
        for item in reversed(table):
            if len(loot) >= maxLootLines - 1 or left < lootFloor:
                break
            if item.name not in used and item.price <= left:
                take(item, left)

    rest = coins - sum(line.coins for line in loot)
    if rest > 0:
        loot.append(CoinsLine(rest))
    loot.sort(key=lambda line: line.coins, reverse=True)
    return loot

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
        "bundleID": piece.bundleID or bundle.bundleID,
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
    scope = Profiles.Scope(guildID, userID)
    def build():
        userItems, appUpdates, itemIDs = AddItems(guildID, userID, [(piece, bundle)])
        return {scope: userItems}, appUpdates, itemIDs[0]
    return await Atomic.AtomicUpdate(guildID, [scope], build)

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

def VoidRecord(itemID: Utils.ItemID, item: dict) -> dict:
    return {
        "itemID": itemID,
        "bundleID": item["bundleID"],
        "slot": item["slot"],
    }

def CleanSearch(current: str) -> str:
    return current.lower().replace("#", "")

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
    rows = await PersistentData.SearchPrefix("userData", f"{scope}:item.", CleanSearch(current), 25, byRarity=True)
    return [
        app_commands.Choice(name=Say(Text.AUTOCOMPLETE_ITEM, itemID=itemID, rarity=FormatRarity(json.loads(row)["rarity"]))[:100], value=itemID)
        for itemID, row in rows
    ]

async def AutocompleteOwnItems(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice]:
    return await _AutocompleteUserItems(interaction, current)

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
