import multiprocessing
import functools
import traceback
import importlib
import inspect
import asyncio
import discord
import signal
import atexit
import time
import sys
import os
import re

from discord.ext import commands
from discord import app_commands
from datetime import datetime

from Database import PersistentUserData
from Database import PersistentAppData
from Database import PersistentData
from Utils import Variables
from Utils import Logger
from Utils import Utils
from Utils.Translation import Say, Text
from Game import TemporaryBuffs
from Game import Profiles
from Game import Drops
from Game import Lists

client: commands.Bot | None = None
botStartTimestamp = -1
hasShutdown = False
backgroundTasks = set()
commandBurst = 5
commandRefillSeconds = 2.0
commandBuckets: dict[Utils.MemberID, tuple[float, float]] = {}

def IsRateLimited(userID: Utils.MemberID) -> bool:
    if userID in Variables.ownerUsers:
        return False
    now = time.monotonic()
    if len(commandBuckets) > 1000:
        refillAll = commandBurst * commandRefillSeconds
        for key in [k for k, (_, last) in commandBuckets.items() if now - last >= refillAll]:
            del commandBuckets[key]
    tokens, last = commandBuckets.get(userID, (commandBurst, now))
    tokens = min(commandBurst, tokens + (now - last) / commandRefillSeconds)
    if tokens < 1:
        commandBuckets[userID] = (tokens, now)
        return True
    commandBuckets[userID] = (tokens - 1, now)
    return False

def FireAndForget(coroutine):
    task = asyncio.create_task(coroutine)
    backgroundTasks.add(task)
    task.add_done_callback(OnTaskDone)

def OnTaskDone(task: asyncio.Task) -> None:
    backgroundTasks.discard(task)
    if task.cancelled() or task.exception() is None:
        return
    error = task.exception()
    details = "".join(traceback.format_exception(error))[-3000:]
    FireAndForget(Logger.LogHeadlessError(f"Background task {task.get_coro().__qualname__} failed: {error!r}\n{details}"))

def FindInteraction(args, kwargs) -> discord.Interaction | None:
    return kwargs.get("interaction") or next((a for a in args if isinstance(a, discord.Interaction)), None)

def HasCommandPermission(interaction: discord.Interaction, **permissions: bool) -> bool:
    if interaction.user.id in Variables.ownerUsers:
        return True
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return False
    return interaction.user.guild_permissions.is_superset(discord.Permissions(**permissions))

def GuardCommand(
    permission: str | None = None,
    requireSetup: bool = False,
    onError=None,
):
    def decorator(func):
        @functools.wraps(func)
        async def guarded(*args, **kwargs):
            interaction = FindInteraction(args, kwargs)
            if interaction is None:
                return None
            try:
                if IsRateLimited(interaction.user.id):
                    await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.RATE_LIMITED), ephemeral=True)
                    return None
                if await IsUserBlacklisted(interaction):
                    return None
                requiredPermission = {
                    permission: True,
                }
                if permission is not None and not HasCommandPermission(interaction, **requiredPermission):
                    await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.NOT_ALLOWED), ephemeral=True)
                    return None
                if requireSetup and await EnsureGuildReady(interaction) is None:
                    return None
                return await func(*args, **kwargs)
            except Utils.CommandAbort:
                return None
            except Exception as e:
                await Logger.LogInteractionError(interaction=interaction, client=GetClient(), message=f"{type(e).__name__}: {e}")
                if onError is not None:
                    await onError(interaction, e)
        return guarded
    return decorator

def AppCommandWithAliases(
    tree,
    name,
    aliases=None,
    description=None,
    variableDescriptions=None,
    commandChoices=None,
    autoComplete=None,
    onError=None,
    guildOnly=False,
    requireSetup=None,
    permission=None,
    **kwargs,
):
    if description:
        kwargs['description'] = description
    if requireSetup is None:
        requireSetup = guildOnly

    def decorator(func):
        renames = {p: re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", p).lower() for p in list(inspect.signature(func).parameters)[1:]}
        renames = {p: n for p, n in renames.items() if p != n}
        if renames:
            func = app_commands.rename(**renames)(func)
        if variableDescriptions:
            func = app_commands.describe(**variableDescriptions)(func)
        if commandChoices:
            func = app_commands.choices(**commandChoices)(func)
        if autoComplete:
            func = app_commands.autocomplete(**autoComplete)(func)

        if not isinstance(tree, app_commands.Group):
            if guildOnly:
                func = app_commands.allowed_installs(guilds=True)(func)
                func = app_commands.guild_only()(func)
            else:
                func = app_commands.allowed_installs(guilds=True, users=True)(func)
                func = app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(func)

        func = GuardCommand(permission=permission, requireSetup=requireSetup, onError=onError)(func)
        command = tree.command(name=name, **kwargs)(func)
        for alias in aliases or ():
            tree.command(name=alias, **kwargs)(func)

        return command
    return decorator

async def IsUserBlacklisted(interaction: discord.Interaction, logUsage: bool = True):
    channelID = interaction.channel_id
    if channelID not in Variables.dontLogChannels and logUsage:
        FireAndForget(Logger.LogCommandUsage(interaction=interaction, client=client))

    if channelID in Variables.blacklistedChannels:
        await Logger.SendInteractionMessage(interaction=interaction, message=Variables.blacklistedChannels[channelID], ephemeral=False)
        return True

    if interaction.guild is not None:
        guildID = interaction.guild.id
        if guildID in Variables.blacklistedGuilds:
            embed = CreateDefaultEmbed(
                createdAt=interaction.created_at,
                title=Say(Text.BOT_BANNED_TITLE),
                description=Variables.blacklistedGuilds[guildID],
            )
            await Logger.SendInteractionMessage(interaction=interaction, embed=embed, ephemeral=False)
            return True

    if interaction.user.id in Variables.blacklistedUsers:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.BLACKLISTED_USER), ephemeral=False)
        return True

    if logUsage:
        totalCommands = PersistentAppData.GetData("totalCommands", 0)
        await PersistentAppData.UpdateData("totalCommands", totalCommands + 1, showMessage=False, durable=False)
    return False

async def EnsureGuildReady(interaction: discord.Interaction):
    config = Utils.GuildConfig(interaction.guild_id)
    if not config.get("dropChannelID"):
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.GUILD_NOT_SET_UP), ephemeral=True)
        return None
    return config

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
        self.add_view(Drops.ClaimView())
        FireAndForget(PersistentData.BackupLoop())
        FireAndForget(PersistentAppData.FlushLoop())
        FireAndForget(PersistentUserData.EvictLoop())
        FireAndForget(TemporaryBuffs.ClockLoop())
        FireAndForget(Logger.WebhookSenderLoop())
        FireAndForget(Drops.SpawnLoop())

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id}) in {time.time() - self.startTime:.2f} seconds')
        if Variables.shouldSyncCommands:
            await self.SyncCommands()

def GetClient():
    assert client is not None, "Client has not been initialized"
    return client

def LoadCommands(folderPath: str):
    for root, folders, filenames in os.walk(folderPath):
        folders[:] = sorted(folder for folder in folders if not folder.startswith(("_", ".")))
        for filename in sorted(filenames):
            if filename.endswith(".py") and not filename.startswith("_"):
                moduleName = os.path.join(root, filename[:-3]).replace(os.sep, ".")
                try:
                    importlib.import_module(moduleName)
                except Exception:
                    FireAndForget(Logger.LogHeadlessError(message=f"Failed to load {moduleName}: {traceback.format_exc()}"))

def EnsureFoldersExist():
    os.makedirs(Variables.LOGS_PATH, exist_ok=True)
    os.makedirs(Variables.PERSISTENT_DATA_BACKUPS_PATH, exist_ok=True)

async def Startup():
    EnsureFoldersExist()
    await PersistentAppData.LoadPersistentAppData()
    TemporaryBuffs.LoadClock()
    await PersistentUserData.LoadPersistentUserData()
    await Profiles.RecoverPendingRolls()

    await Lists.Initialize()

    LoadCommands("Commands")

def Shutdown():
    global hasShutdown
    if hasShutdown:
        return
    hasShutdown = True

    print("Shutdown detected.")
def RequestShutdown(signum=None, frame=None):
    loop = client.loop if client is not None else None
    if isinstance(loop, asyncio.AbstractEventLoop) and loop.is_running():
        loop.call_soon_threadsafe(FireAndForget, ShutdownAndClose())
    else:
        Shutdown()
        sys.exit(0)
async def ShutdownAndClose():
    for step in (
        Drops.ShutdownDrops,
        Logger.CloseSharedSession,
    ):
        try:
            await step()
        except Exception:
            print(f"{step.__name__} failed: {traceback.format_exc()}")
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
        token = file.read().strip()
    if not token:
        print(f"Bot token file is empty: {filePath}")
        Shutdown()
        return

    assert client is not None, "Client is not initialized."
    try:
        await client.start(token)
    finally:
        try:
            await TemporaryBuffs.SaveClock()
            await PersistentAppData.Flush()
        except Exception:
            print(f"Final app data flush failed: {traceback.format_exc()}")
        Shutdown()
