import discord
import os

from dataclasses import dataclass
from enum import StrEnum
from env import *

from Utils.Translation import Say, Text

shouldSyncCommands = True
isTestingBot = True

# Bot
footerText = Say(Text.BOT_FOOTER)
defaultBotName = Say(Text.BOT_NAME)
avatarLink = "https://cdn.discordapp.com/avatars/1424353972545654925/a3e814faa95da96a5307e2e8122748c7.webp"
defaultColorHex = 0x00FF7F
defaultDiscordColor = discord.Color(defaultColorHex)

# Blacklist
blacklistedUsers = []
blacklistedChannels = {}
blacklistedGuilds = {}

# Logger Only
dontLogChannels = [
    1368333867303309362, #cot-bommands
]

# Paths
mainFolderPath = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INPUT_PATH = os.path.join(mainFolderPath, "Input")
TOKENS_PATH = os.path.join(INPUT_PATH, "Tokens")

OUTPUT_PATH = os.path.join(mainFolderPath, "Output")
LOGS_PATH = os.path.join(OUTPUT_PATH, "Logs")
PERSISTENT_DATA_PATH = os.path.join(OUTPUT_PATH, "PersistentData")
PERSISTENT_DATA_BACKUPS_PATH = os.path.join(PERSISTENT_DATA_PATH, "Backups")

# Files
PERSISTENT_DB_FILE_PATH = os.path.join(PERSISTENT_DATA_PATH, "Persistent.db")
COMMAND_LOG_FILE_PATH = os.path.join(LOGS_PATH, "CommandLog.txt")
ERROR_LOG_FILE_PATH = os.path.join(LOGS_PATH, "ErrorLog.txt")
REQUESTS_LOG_FILE_PATH = os.path.join(LOGS_PATH, "RequestsLog.txt")

ITEM_LISTS_PATH = os.path.join(INPUT_PATH, "ItemLists")
ARMOR_IMAGES_PATH = os.path.join(INPUT_PATH, "Images")
ITEM_LIST_FILE_PATH = os.path.join(ITEM_LISTS_PATH, "GeneratedItems.jsonl")
ITEM_LIST_INDEX_FILE_PATH = os.path.join(ITEM_LISTS_PATH, "GeneratedItems.db")

@dataclass(slots=True)
class GameSetting:
    label: str
    description: str
    default: float
    minimum: float
    maximum: float
    isInt: bool = False

class Permission(StrEnum):
    OWNER = "owner"
    MANAGE_SERVER = "manage_guild"

class Setting(StrEnum):
    SPECIAL_ALERT_THRESHOLD = "specialThreshold"
    RARE_ITEM_SKEW = "rareItemSkew"
    TIMED_DROP_LUCK = "timedDropLuck"
    BONUS_BUNDLE_CHANCE = "bonusBundleChance"
    VOID_BONUS_CHANCE = "voidBonusChance"
    BONUS_LUCK = "bonusLuck"
    ROLL_BASE_LUCK = "rollBaseLuck"
    BASE_ROLLS_PER_HOUR = "baseRollsPerHour"
    BASE_ROLL_OVERFLOW = "baseRollOverflow"
    BONUS_COINS_CHANCE = "bonusCoinsChance"
    SELL_COIN_RATE = "sellCoinRate"
    BONUS_COIN_RATE = "bonusCoinRate"
    SHOWCASE_INCOME_RATE = "showcaseIncomeRate"
    STARTING_SHOWCASE_SLOTS = "startingShowcaseSlots"
    STARTING_EARNING_SHOWCASE_SLOTS = "startingEarningShowcaseSlots"
    DROP_INTERVAL_MIN_SECONDS = "dropIntervalMinSeconds"
    DROP_INTERVAL_MAX_SECONDS = "dropIntervalMaxSeconds"
    CLAIM_EXPIRY_SECONDS = "claimExpirySeconds"
    TRADE_TIMEOUT_SECONDS = "tradeTimeoutSeconds"

    @property
    def definition(self) -> GameSetting:
        return SETTINGS[self]

def Define(setting: Setting, default: float, minimum: float, maximum: float, isInt: bool = False) -> tuple[Setting, GameSetting]:
    label = Say(Text[f"SETTING_{setting.name}_LABEL"])
    description = Say(Text[f"SETTING_{setting.name}_DESCRIPTION"])
    return setting, GameSetting(label, description, default, minimum, maximum, isInt)

SETTINGS: dict[str, GameSetting] = dict([
    Define(Setting.SPECIAL_ALERT_THRESHOLD, 20, 1, 50, isInt=True),
    Define(Setting.RARE_ITEM_SKEW, 1, 0, 10),
    Define(Setting.TIMED_DROP_LUCK, 3.0, 0.0, 10.0),
    Define(Setting.ROLL_BASE_LUCK, 1.0, 0.0, 10.0),
    Define(Setting.BONUS_LUCK, 1.5, 0.0, 10.0),
    Define(Setting.BONUS_BUNDLE_CHANCE, 0.05, 0.0, 1.0),
    Define(Setting.VOID_BONUS_CHANCE, 0.05, 0.0, 1.0),
    Define(Setting.BASE_ROLLS_PER_HOUR, 5, 0, 50, isInt=True),
    Define(Setting.BASE_ROLL_OVERFLOW, 1.5, 0.0, 10.0),
    Define(Setting.BONUS_COINS_CHANCE, 0.10, 0.0, 1.0),
    Define(Setting.SELL_COIN_RATE, 20_000_000, 0, 1_000_000_000, isInt=True),
    Define(Setting.BONUS_COIN_RATE, 5_000_000, 0, 1_000_000_000, isInt=True),
    Define(Setting.SHOWCASE_INCOME_RATE, 1_000_000, 0, 1_000_000_000, isInt=True),
    Define(Setting.STARTING_SHOWCASE_SLOTS, 50, 1, 50, isInt=True),
    Define(Setting.STARTING_EARNING_SHOWCASE_SLOTS, 2, 0, 10, isInt=True),
    Define(Setting.DROP_INTERVAL_MIN_SECONDS, 210, 10, 86_400, isInt=True),
    Define(Setting.DROP_INTERVAL_MAX_SECONDS, 450, 10, 86_400, isInt=True),
    Define(Setting.CLAIM_EXPIRY_SECONDS, 300, 10, 900, isInt=True),
    Define(Setting.TRADE_TIMEOUT_SECONDS, 180, 10, 300, isInt=True),
])
