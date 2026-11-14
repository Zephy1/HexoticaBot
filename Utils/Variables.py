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
defaultBotDescription = Say(Text.BOT_DESCRIPTION, BOT_FOOTER=footerText)
defaultBotStatus = {}
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

SETTINGS: dict[str, GameSetting] = {
    Setting.SPECIAL_ALERT_THRESHOLD:   GameSetting(Say(Text.SETTING_SPECIAL_ALERT_THRESHOLD_LABEL), Say(Text.SETTING_SPECIAL_ALERT_THRESHOLD_DESCRIPTION), 20, 1, 50, isInt=True),
    Setting.RARE_ITEM_SKEW:            GameSetting(Say(Text.SETTING_RARE_ITEM_SKEW_LABEL), Say(Text.SETTING_RARE_ITEM_SKEW_DESCRIPTION), 1, 0, 10),
    Setting.TIMED_DROP_LUCK:           GameSetting(Say(Text.SETTING_TIMED_DROP_LUCK_LABEL), Say(Text.SETTING_TIMED_DROP_LUCK_DESCRIPTION), 3.0, 0.0, 10.0),
    Setting.ROLL_BASE_LUCK:            GameSetting(Say(Text.SETTING_ROLL_BASE_LUCK_LABEL), Say(Text.SETTING_ROLL_BASE_LUCK_DESCRIPTION), 1.0, 0.0, 10.0),
    Setting.BONUS_LUCK:                GameSetting(Say(Text.SETTING_BONUS_LUCK_LABEL), Say(Text.SETTING_BONUS_LUCK_DESCRIPTION), 1.5, 0.0, 10.0),
    Setting.BONUS_BUNDLE_CHANCE:       GameSetting(Say(Text.SETTING_BONUS_BUNDLE_CHANCE_LABEL), Say(Text.SETTING_BONUS_BUNDLE_CHANCE_DESCRIPTION), 0.05, 0.0, 1.0),
    Setting.VOID_BONUS_CHANCE:         GameSetting(Say(Text.SETTING_VOID_BONUS_CHANCE_LABEL), Say(Text.SETTING_VOID_BONUS_CHANCE_DESCRIPTION), 0.05, 0.0, 1.0),
    Setting.BASE_ROLLS_PER_HOUR:       GameSetting(Say(Text.SETTING_BASE_ROLLS_PER_HOUR_LABEL), Say(Text.SETTING_BASE_ROLLS_PER_HOUR_DESCRIPTION), 5, 0, 50, isInt=True),
    Setting.BASE_ROLL_OVERFLOW:        GameSetting(Say(Text.SETTING_BASE_ROLL_OVERFLOW_LABEL), Say(Text.SETTING_BASE_ROLL_OVERFLOW_DESCRIPTION), 1.5, 0.0, 10.0),
    Setting.BONUS_COINS_CHANCE:        GameSetting(Say(Text.SETTING_BONUS_COINS_CHANCE_LABEL), Say(Text.SETTING_BONUS_COINS_CHANCE_DESCRIPTION), 0.10, 0.0, 1.0),
    Setting.SELL_COIN_RATE:            GameSetting(Say(Text.SETTING_SELL_COIN_RATE_LABEL), Say(Text.SETTING_SELL_COIN_RATE_DESCRIPTION), 25_000_000, 0, 1_000_000_000, isInt=True),
    Setting.SHOWCASE_INCOME_RATE:      GameSetting(Say(Text.SETTING_SHOWCASE_INCOME_RATE_LABEL), Say(Text.SETTING_SHOWCASE_INCOME_RATE_DESCRIPTION), 1_000_000, 0, 1_000_000_000, isInt=True),
    Setting.STARTING_SHOWCASE_SLOTS:           GameSetting(Say(Text.SETTING_STARTING_SHOWCASE_SLOTS_LABEL), Say(Text.SETTING_STARTING_SHOWCASE_SLOTS_DESCRIPTION), 50, 1, 50, isInt=True),
    Setting.STARTING_EARNING_SHOWCASE_SLOTS:   GameSetting(Say(Text.SETTING_STARTING_EARNING_SHOWCASE_SLOTS_LABEL), Say(Text.SETTING_STARTING_EARNING_SHOWCASE_SLOTS_DESCRIPTION), 2, 0, 10, isInt=True),
    Setting.DROP_INTERVAL_MIN_SECONDS: GameSetting(Say(Text.SETTING_DROP_INTERVAL_MIN_SECONDS_LABEL), Say(Text.SETTING_DROP_INTERVAL_MIN_SECONDS_DESCRIPTION), 210, 10, 86_400, isInt=True),
    Setting.DROP_INTERVAL_MAX_SECONDS: GameSetting(Say(Text.SETTING_DROP_INTERVAL_MAX_SECONDS_LABEL), Say(Text.SETTING_DROP_INTERVAL_MAX_SECONDS_DESCRIPTION), 450, 10, 86_400, isInt=True),
    Setting.CLAIM_EXPIRY_SECONDS:      GameSetting(Say(Text.SETTING_CLAIM_EXPIRY_SECONDS_LABEL), Say(Text.SETTING_CLAIM_EXPIRY_SECONDS_DESCRIPTION), 300, 10, 900, isInt=True),
    Setting.TRADE_TIMEOUT_SECONDS:     GameSetting(Say(Text.SETTING_TRADE_TIMEOUT_SECONDS_LABEL), Say(Text.SETTING_TRADE_TIMEOUT_SECONDS_DESCRIPTION), 45, 10, 300, isInt=True),
}
