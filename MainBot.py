import multiprocessing
import functools
import traceback
import threading
import importlib
import asyncio
import discord
import signal
import atexit
import time
import sys
import os

from discord.ext import commands
from discord import app_commands
from datetime import datetime

from Database import PersistentUserData
from Database import PersistentAppData
from Database import PersistentData
from Utils import Variables
from Utils import Logger
from Utils import Utils

client: commands.Bot|None = None
botStartTimestamp = -1
_shutdownLock = threading.Lock()
_hasShutdown = False
_backgroundTasks = set()
commandBurst = 5
commandRefillSeconds = 2.0
_commandBuckets = {}

def IsRateLimited(userID: int) -> bool:
    if userID in Variables.ownerUsers:
        return False
    now = time.monotonic()
    tokens, last = _commandBuckets.get(userID, (commandBurst, now))
    tokens = min(commandBurst, tokens + (now - last) / commandRefillSeconds)
    if tokens < 1:
        _commandBuckets[userID] = (tokens, now)
        return True
    _commandBuckets[userID] = (tokens - 1, now)
    return False

def FireAndForget(coroutine):
    task = asyncio.create_task(coroutine)
    _backgroundTasks.add(task)
    task.add_done_callback(_backgroundTasks.discard)

def AppCommandWithAliases(tree, name, aliases=None, description=None, variableDescriptions=None, commandChoices=None, autoComplete=None, onError=None, **kwargs):
    aliases = aliases or []
    variableDescriptions = variableDescriptions or {}
    commandChoices = commandChoices or {}
    autoComplete = autoComplete or {}

    if description:
        kwargs['description'] = description

    def decorator(func):
        if variableDescriptions:
            func = app_commands.describe(**variableDescriptions)(func)
        if commandChoices:
            func = app_commands.choices(**commandChoices)(func)
        if autoComplete:
            func = app_commands.autocomplete(**autoComplete)(func)

        func = app_commands.allowed_installs(**{"guilds": True, "users": True})(func)
        func = app_commands.allowed_contexts(**{"guilds": True, "dms": True, "private_channels": True})(func)

        def _makeGuarded():
            @functools.wraps(func)
            async def guarded(interaction, *args, **kw):
                if IsRateLimited(interaction.user.id):
                    await Logger.SendInteractionMessage(interaction=interaction, message="You are using commands too quickly. Try again in a few seconds.", ephemeral=True)
                    return
                try:
                    return await func(interaction, *args, **kw)
                except Exception as e:
                    await Logger.LogInteractionError(interaction=interaction, client=GetClient(), message=f"Unhandled exception occurred: {e}")
                    if onError is not None:
                        await onError(interaction, e)
            return guarded

        command = tree.command(name=name, **kwargs)(_makeGuarded())

        for alias in aliases:
            tree.command(name=alias, **kwargs)(_makeGuarded())

        return command
    return decorator

async def isUserOwner(interaction: discord.Interaction, shouldLog: bool = True):
    channelID = interaction.channel.id
    if channelID not in Variables.dontLogChannels and shouldLog:
        FireAndForget(Logger.LogCommandUsage(interaction=interaction, client=client))

    if interaction.user.id not in Variables.ownerUsers:
        await Logger.SendInteractionMessage(interaction=interaction, message="You do not have permission to use this command.", ephemeral=True)
        return False
    return True

async def isUserBlacklisted(interaction: discord.Interaction):
    channelID = interaction.channel.id
    if channelID not in Variables.dontLogChannels:
        FireAndForget(Logger.LogCommandUsage(interaction=interaction, client=client))

    if channelID in Variables.blacklistedChannels:
        await Logger.SendInteractionMessage(interaction=interaction, message=Variables.blacklistedChannels[channelID], ephemeral=False)
        return True

    if interaction.guild is not None:
        guildID = interaction.guild.id
        if guildID in Variables.blacklistedGuilds:
            embed = CreateDefaultEmbed(
                createdAt=interaction.created_at,
                title="Bot Banned",
                description=Variables.blacklistedGuilds[guildID],
            )
            await Logger.SendInteractionMessage(interaction=interaction, embed=embed, ephemeral=False)
            return True

    userID = interaction.user.id
    isBlacklisted = userID in Variables.blacklistedUsers
    if isBlacklisted:
        await Logger.SendInteractionMessage(interaction=interaction, message="😢", ephemeral=False)
        return True

    totalCommands = PersistentAppData.GetData("totalCommands", 0)
    await PersistentAppData.UpdateData("totalCommands", totalCommands + 1, showMessage=False, durable=False)
    return False

def CreateDefaultEmbed(
    title: str,
    description: str,
    createdAt: datetime = None,
    color: discord.Color = None,
    thumbnailLink: str = None,
    titleLink: str = None,
) -> discord.Embed:
    if color is None:
        color = Variables.defaultDiscordColor

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )

    embed.set_footer(text=Variables.footerText, icon_url=Variables.avatarLink)
    if thumbnailLink:
        embed.set_thumbnail(url=thumbnailLink)
        embed._colour = color
    if createdAt:
        embed.timestamp = createdAt
    if titleLink:
        embed.url = titleLink
    return embed

class Client(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.startTime = time.time()

    async def SyncCommands(self):
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} - {synced} commands")
            return True, len(synced)
        except Exception:
            print(f"Failed to sync commands: {traceback.format_exc()}")
        return False, None

    async def setup_hook(self):
        FireAndForget(PersistentData.BackupLoop())
        FireAndForget(PersistentAppData.FlushLoop())
        FireAndForget(PersistentUserData.EvictLoop())
        FireAndForget(Logger.WebhookSenderLoop())

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id}) in {time.time() - self.startTime:.2f} seconds')
        if Variables.shouldSyncCommands:
            await self.SyncCommands()

def GetClient():
    assert client is not None, "Client has not been initialized"
    return client

def LoadCommands(folderPath: str):
    for filename in os.listdir(folderPath):
        if filename.endswith(".py") and not filename.startswith("_"):
            moduleName = os.path.join(folderPath, filename[:-3]).replace(os.sep, ".").replace("/", ".")
            try:
                importlib.import_module(moduleName)
            except Exception as e:
                print(f"Failed to load {moduleName}: {e}")

def EnsureFoldersExist():
    os.makedirs(Variables.LOGS_PATH, exist_ok=True)
    os.makedirs(Variables.OUTPUT_PATH, exist_ok=True)
    os.makedirs(Variables.PERSISTENT_DATA_PATH, exist_ok=True)
    os.makedirs(Variables.PERSISTENT_DATA_BACKUPS_PATH, exist_ok=True)

async def Startup():
    EnsureFoldersExist()
    await PersistentAppData.LoadPersistentAppData()
    await PersistentUserData.LoadPersistentUserData()

    LoadCommands("Commands")

def Shutdown():
    global _hasShutdown
    with _shutdownLock:
        if _hasShutdown:
            return
        _hasShutdown = True

    print("Shutdown detected")
def RequestShutdown(signum=None, frame=None):
    if client is not None and client.loop is not None and client.loop.is_running():
        client.loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(_ShutdownAndClose())
        )
    else:
        Shutdown()
        sys.exit(0)
async def _ShutdownAndClose():
    try:
        await Utils.CloseSharedSession()
    except Exception:
        print(f"Async export failed: {traceback.format_exc()}")
    await client.close()
if multiprocessing.parent_process() is None:
    signal.signal(signal.SIGINT, RequestShutdown)
    signal.signal(signal.SIGTERM, RequestShutdown)
    atexit.register(Shutdown)

async def Main():
    global client
    global botStartTimestamp
    Logger.mainLoop = asyncio.get_running_loop()
    intents = discord.Intents.none()
    intents.guilds = True
    client = Client(command_prefix='!', intents=intents)
    botStartTimestamp = datetime.now()

    await Startup()

    filePath = os.path.join(Variables.TOKENS_PATH, "BotToken" if not Variables.isTestingBot else "TestingBotToken")
    with open(filePath) as file:
        assert client is not None, "Client is not initialized."
        try:
            await client.start(file.read().strip())
        finally:
            try:
                await PersistentAppData.Flush()
            except Exception:
                print(f"Final app data flush failed: {traceback.format_exc()}")
            Shutdown()
