import platform
import discord
import os

from env import *

shouldSyncCommands = False
isTestingBot = True

slashType = "\\" if platform.system() == "Windows" else "/"

# Bot
footerText = "Made by ze.phy"
defaultBotName = "Hexotica"
defaultBotDescription = (
    "\ud83c\udfa8 Hexotica"
    "\n"
    "\n"
    "Commands:"
    "\n"
    f"\n**{footerText}**"
)
defaultBotStatus = {}
avatarLink = "https://cdn.discordapp.com/avatars/1424353972545654925/a3e814faa95da96a5307e2e8122748c7.webp"
defaultColorHex = 0x00FF7F
defaultDiscordColor = discord.Color(defaultColorHex)
defaultHeaders = {
    "User-Agent": "Mozilla/5.0 (Hexotica)",
    "Content-Type": "application/json",
}

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
