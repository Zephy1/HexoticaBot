import MainBot

import functools
import asyncio
import discord
import time
import math
import re

from dataclasses import dataclass
from typing import NoReturn
from enum import StrEnum

from Database import PersistentAppData

from .Translation import Say, Text
from . import Variables
from . import Logger

# Discord Types
GuildID = int
ChannelID = int
MessageID = int
MemberID = int

# Game Types
UserScope = str
ItemType = str
HexCode = str
ItemID = str
ItemIndex = int
SlotIndex = int
BundleID = str
Setting = Variables.Setting
SettingName = str
SendableChannel = discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread
Coins = int

validEmptyHexStrings = [
    "empty",
    "blank",
    "none",
    "default",
    "nothing",
    "n/a",
    "na",
]
validAnyHexStrings = [
    "any",
    "all",
    "everything",
    "none",
    "blank",
    "all_items",
    "everyitem",
]

HEX_CODE_REGEX = re.compile(r"[0-9A-F]{1,6}")

class ArmorSlot(StrEnum):
    HELMET = "HELMET"
    CHESTPLATE = "CHESTPLATE"
    LEGGINGS = "LEGGINGS"
    BOOTS = "BOOTS"

    @classmethod
    def _missing_(cls, value):
        return cls.__members__.get(value.strip().upper()) if isinstance(value, str) else None

class ColorType(StrEnum):
    Exotic = "Exotic"
    PureDye = "Pure"
    TrueDye = "True"
    OtherTrueDye = "OtherTrue"
    Fairy = "Fairy"
    # OGFairy = "OG Fairy"
    Crystal = "Crystal"
    Armor = "Armor"
    Bleached = "Bleached"
    _None = "None"

    def __str__(self):
        return self.value

class ArmorType(StrEnum):
    # Unsorted
    ANGLER = "ANGLER"
    BACKWATER = "BACKWATER"
    MAGMA = "MAGMA"
    SPOOKY = "SPOOKY"
    BAT_PERSON = "BAT_PERSON"
    BLAZE = "BLAZE"
    FROZEN_BLAZE = "FROZEN_BLAZE"
    CACTUS = "CACTUS"
    CHEAP_TUXEDO = "CHEAP_TUXEDO"
    FANCY_TUXEDO = "FANCY_TUXEDO"
    ELEGANT_TUXEDO = "ELEGANT_TUXEDO"
    PACK_HELMET = "PACK"
    PACK_CHESTPLATE = "PACK"
    CRYSTAL = "CRYSTAL"
    EMERALD = "EMERALD"
    FAIRY = "FAIRY"
    FARMER_BOOTS = "FARMER_BOOTS"
    RANCHER_BOOTS = "RANCHER_BOOTS"
    FARM_SUIT = "FARM_SUIT"
    FARM_ARMOR = "FARM_ARMOR"
    GROWTH = "GROWTH"
    MASTIFF = "MASTIFF"
    GUARDIAN_CHESTPLATE = "GUARDIAN_CHESTPLATE"
    CREEPER_PANTS = "CREEPER_PANTS"
    LAPIS = "LAPIS"
    LEAFLET = "LEAFLET"
    MINER = "MINER"
    MUSHROOM = "MUSHROOM"
    BIOHAZARD = "BIOHAZARD"
    STEREO_PANTS = "STEREO_PANTS"
    OBSIDIAN_CHESTPLATE = "OBSIDIAN_CHESTPLATE"
    PUMPKIN = "PUMPKIN"
    SPONGE = "SPONGE"
    SHARK = "SHARK"
    SPEEDSTER = "SPEEDSTER"
    SQUID_BOOTS = "SQUID_BOOTS"
    TARANTULA = "TARANTULA"
    SUPERIOR = "SUPERIOR"
    YOUNG = "YOUNG"
    WISE = "WISE"
    UNSTABLE = "UNSTABLE"
    PROTECTOR = "PROTECTOR"
    OLD = "OLD"
    STRONG = "STRONG"

    # Rarity 1

    # Rarity 2

    # Rarity 3

    # Rarity 4

    # Rarity 5

    # Rarity Max

@dataclass(frozen=True)
class ArmorSet:
    pieces: dict[ArmorSlot, float]

    @property
    def size(self) -> int:
        return len(self.pieces)

    @property
    def pos(self) -> list[float]:
        return list(self.pieces.values())

    def to_shape(self, **overrides) -> dict:
        return {"size": self.size, "pos": self.pos, **overrides}

    def describe(self, pattern) -> list[ArmorSlot]:
        return [slot for slot, kept in zip(self.pieces, pattern) if kept]

ARMOR_SETS: dict[ArmorType, ArmorSet] = {
    ArmorType.MAGMA: ArmorSet({  # 180,000
        ArmorSlot.HELMET: 24.50,
        ArmorSlot.CHESTPLATE: 25.37,
        ArmorSlot.LEGGINGS: 25.39,
        ArmorSlot.BOOTS: 24.75,
    }),
    ArmorType.LAPIS: ArmorSet({  # 175,000
        ArmorSlot.CHESTPLATE: 34.19,
        ArmorSlot.LEGGINGS: 33.36,
        ArmorSlot.BOOTS: 32.44,
    }),
    ArmorType.MINER: ArmorSet({  # 67,500
        ArmorSlot.HELMET: 24.52,
        ArmorSlot.CHESTPLATE: 25.40,
        ArmorSlot.LEGGINGS: 25.15,
        ArmorSlot.BOOTS: 24.93,
    }),
    ArmorType.OBSIDIAN_CHESTPLATE: ArmorSet({  # 67,500
        ArmorSlot.CHESTPLATE: 100,
    }),
    ArmorType.STRONG: ArmorSet({  # 60,000
        ArmorSlot.CHESTPLATE: 32.01,
        ArmorSlot.LEGGINGS: 33.77,
        ArmorSlot.BOOTS: 34.22,
    }),
    ArmorType.UNSTABLE: ArmorSet({  # 55,000
        ArmorSlot.CHESTPLATE: 34.10,
        ArmorSlot.LEGGINGS: 32.40,
        ArmorSlot.BOOTS: 33.50,
    }),
    ArmorType.GUARDIAN_CHESTPLATE: ArmorSet({  # 48,500
        ArmorSlot.CHESTPLATE: 100,
    }),
    ArmorType.CREEPER_PANTS: ArmorSet({  # 48,000
        ArmorSlot.LEGGINGS: 100,
    }),
    ArmorType.ANGLER: ArmorSet({  # 45,000
        ArmorSlot.CHESTPLATE: 33.40,
        ArmorSlot.LEGGINGS: 33.90,
        ArmorSlot.BOOTS: 32.70,
    }),
    ArmorType.YOUNG: ArmorSet({  # 39,500
        ArmorSlot.CHESTPLATE: 33.82,
        ArmorSlot.LEGGINGS: 31.46,
        ArmorSlot.BOOTS: 34.72,
    }),
    ArmorType.OLD: ArmorSet({  # 38,500
        ArmorSlot.CHESTPLATE: 34.17,
        ArmorSlot.LEGGINGS: 32.90,
        ArmorSlot.BOOTS: 32.93,
    }),
    ArmorType.PROTECTOR: ArmorSet({  # 34,000
        ArmorSlot.CHESTPLATE: 33.16,
        ArmorSlot.LEGGINGS: 33.52,
        ArmorSlot.BOOTS: 33.32,
    }),
    ArmorType.WISE: ArmorSet({  # 30,500
        ArmorSlot.CHESTPLATE: 31.86,
        ArmorSlot.LEGGINGS: 32.63,
        ArmorSlot.BOOTS: 35.51,
    }),
    ArmorType.STEREO_PANTS: ArmorSet({  # 22,750
        ArmorSlot.LEGGINGS: 100,
    }),
    ArmorType.SUPERIOR: ArmorSet({  # 15,000
        ArmorSlot.CHESTPLATE: 30.71,
        ArmorSlot.LEGGINGS: 30.09,
        ArmorSlot.BOOTS: 39.20,
    }),
    ArmorType.SPEEDSTER: ArmorSet({  # 13,750
        ArmorSlot.HELMET: 23.86,
        ArmorSlot.CHESTPLATE: 24.00,
        ArmorSlot.LEGGINGS: 25.50,
        ArmorSlot.BOOTS: 26.64,
    }),
    ArmorType.MUSHROOM: ArmorSet({  # 13,000
        ArmorSlot.HELMET: 23.95,
        ArmorSlot.CHESTPLATE: 25.32,
        ArmorSlot.LEGGINGS: 25.32,
        ArmorSlot.BOOTS: 25.40,
    }),
    ArmorType.EMERALD: ArmorSet({  # 9,750
        ArmorSlot.HELMET: 25.41,
        ArmorSlot.CHESTPLATE: 25.10,
        ArmorSlot.LEGGINGS: 24.49,
        ArmorSlot.BOOTS: 25.00,
    }),
    ArmorType.FARMER_BOOTS: ArmorSet({  # 7,000
        ArmorSlot.BOOTS: 100,
    }),
    ArmorType.SQUID_BOOTS: ArmorSet({  # 5,750
        ArmorSlot.BOOTS: 100,
    }),
    ArmorType.RANCHER_BOOTS: ArmorSet({  # 3,750
        ArmorSlot.BOOTS: 100,
    }),
    ArmorType.FARM_SUIT: ArmorSet({  # 3,500
        ArmorSlot.HELMET: 19.61,
        ArmorSlot.CHESTPLATE: 27.90,
        ArmorSlot.LEGGINGS: 28.45,
        ArmorSlot.BOOTS: 24.03,
    }),
    ArmorType.LEAFLET: ArmorSet({  # 2,200
        ArmorSlot.CHESTPLATE: 33.94,
        ArmorSlot.LEGGINGS: 35.76,
        ArmorSlot.BOOTS: 30.30,
    }),
    ArmorType.TARANTULA: ArmorSet({  # 1,650
        ArmorSlot.HELMET: 51.85,
        ArmorSlot.LEGGINGS: 48.15,
    }),
    ArmorType.CACTUS: ArmorSet({  # 1,650
        ArmorSlot.HELMET: 23.08,
        ArmorSlot.CHESTPLATE: 27.22,
        ArmorSlot.LEGGINGS: 23.67,
        ArmorSlot.BOOTS: 26.04,
    }),
    ArmorType.FARM_ARMOR: ArmorSet({  # 1,550
        ArmorSlot.CHESTPLATE: 31.03,
        ArmorSlot.LEGGINGS: 34.48,
        ArmorSlot.BOOTS: 34.48,
    }),
    ArmorType.GROWTH: ArmorSet({  # 1,100
        ArmorSlot.HELMET: 20.72,
        ArmorSlot.CHESTPLATE: 25.23,
        ArmorSlot.LEGGINGS: 25.23,
        ArmorSlot.BOOTS: 28.83,
    }),
    ArmorType.PUMPKIN: ArmorSet({  # 550
        ArmorSlot.CHESTPLATE: 36.00,
        ArmorSlot.LEGGINGS: 36.00,
        ArmorSlot.BOOTS: 28.00,
    }),
    ArmorType.FAIRY: ArmorSet({  # 300
        ArmorSlot.HELMET: 14.81,
        ArmorSlot.CHESTPLATE: 33.33,
        ArmorSlot.LEGGINGS: 25.93,
        ArmorSlot.BOOTS: 25.93,
    }),
    ArmorType.BIOHAZARD: ArmorSet({  # 250
        ArmorSlot.CHESTPLATE: 40.63,
        ArmorSlot.LEGGINGS: 31.25,
        ArmorSlot.BOOTS: 28.13,
    }),
    ArmorType.BAT_PERSON: ArmorSet({  # 175
        ArmorSlot.CHESTPLATE: 40.63,
        ArmorSlot.LEGGINGS: 31.25,
        ArmorSlot.BOOTS: 28.13,
    }),
    ArmorType.CHEAP_TUXEDO: ArmorSet({  # 150
        ArmorSlot.CHESTPLATE: 50.00,
        ArmorSlot.LEGGINGS: 30.00,
        ArmorSlot.BOOTS: 20.00,
    }),
    ArmorType.PACK_CHESTPLATE: ArmorSet({  # 125
        ArmorSlot.CHESTPLATE: 100,
    }),
    ArmorType.BACKWATER: ArmorSet({  # 100
        ArmorSlot.CHESTPLATE: 40.63,
        ArmorSlot.LEGGINGS: 31.25,
        ArmorSlot.BOOTS: 28.13,
    }),
    ArmorType.CRYSTAL: ArmorSet({  # 100
        ArmorSlot.HELMET: 14.81,
        ArmorSlot.CHESTPLATE: 33.33,
        ArmorSlot.LEGGINGS: 25.93,
        ArmorSlot.BOOTS: 25.93,
    }),
    ArmorType.BLAZE: ArmorSet({  # 75
        ArmorSlot.CHESTPLATE: 50.00,
        ArmorSlot.LEGGINGS: 18.75,
        ArmorSlot.BOOTS: 31.25,
    }),
    ArmorType.FROZEN_BLAZE: ArmorSet({  # 50
        ArmorSlot.CHESTPLATE: 50.00,
        ArmorSlot.LEGGINGS: 18.75,
        ArmorSlot.BOOTS: 31.25,
    }),
    ArmorType.FANCY_TUXEDO: ArmorSet({  # 40
        ArmorSlot.CHESTPLATE: 50.00,
        ArmorSlot.LEGGINGS: 30.00,
        ArmorSlot.BOOTS: 20.00,
    }),
    ArmorType.SPOOKY: ArmorSet({  # 40
        ArmorSlot.CHESTPLATE: 31.25,
        ArmorSlot.LEGGINGS: 18.75,
        ArmorSlot.BOOTS: 50.00,
    }),
    ArmorType.SPONGE: ArmorSet({  # 35
        ArmorSlot.CHESTPLATE: 40.63,
        ArmorSlot.LEGGINGS: 31.25,
        ArmorSlot.BOOTS: 28.13,
    }),
    ArmorType.PACK_HELMET: ArmorSet({  # 20
        ArmorSlot.HELMET: 100,
    }),
    ArmorType.ELEGANT_TUXEDO: ArmorSet({  # 20
        ArmorSlot.CHESTPLATE: 50.00,
        ArmorSlot.LEGGINGS: 30.00,
        ArmorSlot.BOOTS: 20.00,
    }),
    ArmorType.MASTIFF: ArmorSet({  # 5
        ArmorSlot.CHESTPLATE: 40.63,
        ArmorSlot.LEGGINGS: 31.25,
        ArmorSlot.BOOTS: 28.13,
    }),
    ArmorType.SHARK: ArmorSet({  # 5
        ArmorSlot.CHESTPLATE: 40.63,
        ArmorSlot.LEGGINGS: 31.25,
        ArmorSlot.BOOTS: 28.13,
    }),
}

@dataclass(frozen=True, slots=True)
class HexColor:
    hexCode: str
    rgb: tuple[int, int, int]
    isBlank: bool = False

    BLANK = None

    def __str__(self) -> str:
        return "Blank" if self.isBlank else f"#{self.hexCode}"

    @property
    def rgbInt(self) -> int:
        return self.rgb[0] << 16 | self.rgb[1] << 8 | self.rgb[2]

    @property
    def signature(self) -> str:
        return f"{self.hexCode[0]}{self.hexCode[2]}{self.hexCode[4]}"
HexColor.BLANK = HexColor(hexCode="000000", rgb=(0, 0, 0), isBlank=True)

def RGBToHex(rgb) -> str:
    if not isinstance(rgb, (list, tuple)) or len(rgb) != 3:
        raise ValueError("RGB must be 3 values.")
    if not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in rgb):
        raise ValueError("RGB values must be ints in 0-255.")
    return "%02X%02X%02X" % tuple(rgb)

def IntToHex(value: int) -> str:
    if not 0 <= value <= 0xFFFFFF:
        raise ValueError("Int must be in 0-0xFFFFFF.")
    return "%06X" % value

def FromHexCode(hexCode: str) -> HexColor:
    rgb = (int(hexCode[0:2], 16), int(hexCode[2:4], 16), int(hexCode[4:6], 16))
    return HexColor(hexCode=hexCode, rgb=rgb)

@functools.lru_cache(maxsize=2048)
def ParseHexCodeString(key: str) -> HexColor:
    if key in validEmptyHexStrings or key in validAnyHexStrings:
        return HexColor.BLANK

    cleaned = key.removeprefix("#").upper()
    if not HEX_CODE_REGEX.fullmatch(cleaned):
        raise ValueError(f"Invalid hex code '{key}'.")
    return FromHexCode(cleaned.rjust(6, "0"))

def GetHexColor(value: "HexColor | str | list[int] | tuple[int, ...] | int") -> HexColor:
    if isinstance(value, HexColor):
        return value
    if value is None or isinstance(value, bool):
        raise ValueError("Invalid hex code.")
    if isinstance(value, (list, tuple)):
        return FromHexCode(RGBToHex(value))
    if isinstance(value, int):
        return FromHexCode(IntToHex(value))
    if isinstance(value, str):
        key = value.strip().lower()
        if not key:
            raise ValueError("Invalid hex code.")
        return ParseHexCodeString(key)
    raise TypeError(f"Unsupported color type: {type(value).__name__}")

def TryGetHexColor(value) -> HexColor | None:
    try:
        return GetHexColor(value)
    except (ValueError, TypeError):
        return None

def GetHexColorListFromString(text: str) -> list[HexColor]:
    colors = [GetHexColor(token) for token in text.split()]
    if not colors:
        raise ValueError("No hex colors found.")
    return colors

def GetNowTimestamp():
    return int(time.time() * 1000)

def MinMaxHexInt(hexInt: int) -> int:
    return min(max(hexInt, 0), 16777215)

MakeNameSafe = Logger.MakeNameSafe

def NormalizeUUID(uuid):
    return uuid.replace("-", "").lower()

def SyncStartCoroutine(coroutine):
    try:
        asyncio.run_coroutine_threadsafe(coroutine, Logger.mainLoop)
    except Exception:
        pass

def OffloadBlocking(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)
    return wrapper

def PluralS(amount: float) -> str:
    return "" if amount == 1 else "s"

def FormatNumber(number: float, valueType: type = int) -> str:
    if valueType is float:
        return f"{number:,.2f}"
    return f"{int(number):,}"

SI_SYMBOL = ["", "k", "M", "B", "T", "P", "E"]
def CompactNumber(number):
    if number == 0:
        return number

    tier = int(math.log10(abs(number)) / 3)

    if tier == 0:
        return number

    suffix = SI_SYMBOL[tier]
    scale = 10 ** (tier * 3)

    scaled = number / scale
    i = 2
    scaled_f = f"{scaled:.{i}f}"
    length_f = len(scaled_f)
    while scaled_f[length_f - 1:length_f] == "0":
        i -= 1
        scaled_f = f"{scaled:.{i}f}"
        length_f = len(scaled_f)
        if i == 0:
            break

    return f"{scaled:.{i}f}{suffix}"

MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "t": 1_000_000_000_000,
}
def UncompactNumber(abbr_number: str) -> float:
    multiplier = MULTIPLIERS.get(abbr_number[-1].lower())
    return float(abbr_number[:-1]) * multiplier if multiplier else float(abbr_number)

def TimedFunction(
    label,
    fn,
    *args,
    **kwargs,
):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    print(f"{label}: {time.perf_counter()-t0:.2f}s")
    return result
async def TimedCoroutine(label, coro):
    t0 = time.perf_counter()
    result = await coro
    print(f"{label}: {time.perf_counter()-t0:.2f}s")
    return result

def CurrentHour() -> int:
    return int(time.time() // 3600)

def GetSettingValue(guildConfig: dict | None, name: SettingName):
    definition = Variables.SETTINGS[name]
    raw = (guildConfig or {}).get("settings", {}).get(name, definition.default)
    value = min(max(raw, definition.minimum), definition.maximum)
    return int(value) if definition.isInt else value

def GetSettingValueFromGuild(guildID: GuildID, name: SettingName):
    return GetSettingValue(PersistentAppData.PeekData(f"guildConfig.{guildID}"), name)

async def SetSetting(
    guildID: GuildID,
    name: SettingName,
    value: float | None,
) -> None:
    definition = Variables.SETTINGS.get(name)
    if definition is None:
        raise ValueError(Say(Text.SETTING_UNKNOWN, name=name))
    if value is not None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(Say(Text.FIELD_NOT_NUMBER, field=definition.label))
        if not definition.minimum <= value <= definition.maximum:
            raise ValueError(Say(Text.FIELD_RANGE, field=definition.label, low=definition.minimum, high=definition.maximum))
        if definition.isInt and value != int(value):
            raise ValueError(Say(Text.FIELD_NOT_INTEGER, field=definition.label))
    config = PersistentAppData.GetData(f"guildConfig.{guildID}", {})
    settings = config.setdefault("settings", {})
    if value is None:
        settings.pop(str(name), None)
    else:
        settings[str(name)] = value
    await PersistentAppData.UpdateData(f"guildConfig.{guildID}", config, showMessage=False)

def GuildConfig(guildID: GuildID) -> dict:
    return PersistentAppData.PeekData(f"guildConfig.{guildID}") or {}

def FormatSetting(name: SettingName, value) -> str:
    definition = Variables.SETTINGS[name]
    return FormatNumber(value, int) if definition.isInt else f"{value:g}"

async def AutocompleteSettings(
    interaction: discord.Interaction,
    current: str,
) -> list[discord.app_commands.Choice]:
    current = current.lower()
    return [discord.app_commands.Choice(name=definition.label, value=str(name))
        for name, definition in Variables.SETTINGS.items()
        if current in name.lower() or current in definition.label.lower()][:25]

class CommandAbort(Exception):
    pass

def IsValidGuild(guildID: GuildID | None) -> bool:
    return guildID is not None and MainBot.GetClient().get_guild(guildID) is not None

async def IsValidMember(guildID: GuildID | None, memberID: MemberID | None) -> bool:
    guild = None if guildID is None else MainBot.GetClient().get_guild(guildID)
    if guild is None or memberID is None:
        return False
    if guild.get_member(memberID) is not None:
        return True
    try:
        await guild.fetch_member(memberID)
    except discord.NotFound:
        return False
    return True

async def AbortCommand(interaction: discord.Interaction, message: str) -> NoReturn:
    await Logger.SendInteractionMessage(interaction=interaction, message=message, ephemeral=True)
    raise CommandAbort

async def RequireGuild(guildID: GuildID | None, interaction: discord.Interaction) -> GuildID:
    if guildID is not None and IsValidGuild(guildID):
        return guildID
    await AbortCommand(interaction, Say(Text.NOT_IN_GUILD))

async def RequireMember(guildID: GuildID, memberID: MemberID | None, interaction: discord.Interaction) -> MemberID:
    if memberID is not None and await IsValidMember(guildID, memberID):
        return memberID
    await AbortCommand(interaction, Say(Text.NOT_A_MEMBER))

async def RequireChannelID(channelID: ChannelID | None, interaction: discord.Interaction) -> ChannelID:
    if channelID is not None:
        return channelID
    await AbortCommand(interaction, Say(Text.NOT_IN_CHANNEL))

async def RequireChannel(interaction: discord.Interaction) -> SendableChannel:
    channel = interaction.channel
    if not isinstance(channel, SendableChannel):
        await AbortCommand(interaction, Say(Text.NOT_IN_CHANNEL))
    permissions = interaction.app_permissions
    if not (permissions.send_messages_in_threads if isinstance(channel, discord.Thread) else permissions.send_messages):
        await AbortCommand(interaction, Say(Text.ROLL_NO_PERMISSION))
    return channel

async def RequireGuildAndMember(guildID: GuildID | None, memberID: MemberID | None, interaction: discord.Interaction) -> tuple[GuildID, MemberID]:
    guildID = await RequireGuild(guildID, interaction)
    memberID = await RequireMember(guildID, memberID, interaction)
    return guildID, memberID
