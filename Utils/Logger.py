import collections
import traceback
import datetime
import aiohttp
import asyncio
import discord
import time

from Utils.Translation import Say, Text
from Utils import Variables

def MakeNameSafe(name):
    if name is None:
        return "Unknown"
    if type(name) == str:
        name = name.encode('ascii', 'replace').decode('ascii')
    return str(name).replace("_", "\\_")

sharedSession: aiohttp.ClientSession | None = None
async def GetSharedSession() -> aiohttp.ClientSession:
    global sharedSession
    if sharedSession is None or sharedSession.closed:
        sharedSession = aiohttp.ClientSession()
    return sharedSession

async def CloseSharedSession():
    global sharedSession
    if sharedSession is not None and not sharedSession.closed:
        await sharedSession.close()
    sharedSession = None

async def SendInteractionMessage(
    interaction: discord.Interaction,
    message: str = None,
    embed: discord.Embed = discord.utils.MISSING,
    discordFile: discord.File = discord.utils.MISSING,
    discordFiles: list[discord.File] = discord.utils.MISSING,
    ephemeral: bool = False,
    view: discord.ui.View = discord.utils.MISSING,
    allowed_mentions: discord.AllowedMentions = discord.utils.MISSING
):
    noEmbed = embed is None or embed is discord.utils.MISSING
    noAttachments = discordFile is discord.utils.MISSING and discordFiles is discord.utils.MISSING
    if message is None and noEmbed and noAttachments and view is discord.utils.MISSING:
        message = "Error: No message or embed provided."

    try:
        if not interaction.response.is_done():
            return await interaction.response.send_message(content=message, embed=embed, file=discordFile, files=discordFiles, ephemeral=ephemeral, view=view, allowed_mentions=allowed_mentions)
        else:
            return await interaction.followup.send(content=message, embed=embed, file=discordFile, files=discordFiles, ephemeral=ephemeral, view=view, allowed_mentions=allowed_mentions, wait=True)
    except Exception as e:
        await LogError(interaction, f"Error sending interaction message: {e}")
async def EditInteractionMessage(
    interaction: discord.Interaction,
    message: str = None,
    embed: discord.Embed = discord.utils.MISSING,
    discordFile: discord.File = discord.utils.MISSING,
    discordFiles: list[discord.File] = discord.utils.MISSING,
    view: discord.ui.View | None = discord.utils.MISSING,
):
    if embed is None and message is None:
        message = "Error: No message or embed provided."

    try:
        attachments = []
        if discordFile is not discord.utils.MISSING:
            attachments.append(discordFile)
        if discordFiles is not discord.utils.MISSING:
            attachments.extend(discordFiles)

        if not interaction.response.is_done():
            return await interaction.response.edit_message(content=message, embed=embed, attachments=attachments, view=view)
        else:
            return await interaction.edit_original_response(content=message, embed=embed, attachments=attachments, view=view)
    except Exception as e:
        await LogError(interaction, f"Error editing interaction message: {e}")

async def Reply(interaction: discord.Interaction, message: str) -> None:
    await SendInteractionMessage(interaction=interaction, message=message, ephemeral=True)

async def LogInteractionError(
    interaction: discord.Interaction,
    message: str,
):
    await SendInteractionMessage(interaction, message=Say(Text.COMMAND_ERROR, error=message), ephemeral=True)
    await LogError(interaction, message)

def GetUserInfoFromInteraction(interaction):
    user = interaction.user

    userID = user.id
    userName = user.name
    userDisplayName = user.display_name if hasattr(user, 'display_name') else user.name

    return {
        "userID": MakeNameSafe(userID),
        "userName": MakeNameSafe(userName),
        "userDisplayName": MakeNameSafe(userDisplayName),
    }
def GetCommandInfoFromInteraction(
    interaction: discord.Interaction,
):
    commandName = interaction.command.name if interaction.command else 'Unknown'
    commandOptions = {k: v for k, v in interaction.namespace.__dict__.items() if not k.startswith('_')}

    copyableCommand = f"/{commandName} "
    for key, value in commandOptions.items():
        copyableCommand += f"{key}: {value} "
    copyableCommand = copyableCommand.strip()

    commandInfo = {
        "commandName": MakeNameSafe(commandName),
        "commandOptions": MakeNameSafe(commandOptions),
        "copyableCommand": MakeNameSafe(copyableCommand)
    }
    return commandInfo
guildNameTtlSeconds = 60 * 60
guildNameFailTtlSeconds = 10 * 60
guildNames = {}
async def GetGuildInfoFromInteraction(interaction: discord.Interaction):
    guild = interaction.guild
    guildName = "DM"
    if guild:
        cached = guildNames.get(guild.id)
        if cached is None or cached[0] < time.monotonic():
            try:
                name = (await interaction.client.fetch_guild_preview(guild.id)).name
            except Exception:
                name = None
            cached = guildNames[guild.id] = (time.monotonic() + (guildNameTtlSeconds if name else guildNameFailTtlSeconds), name)
        guildName = cached[1] or guild.name

    guildID = guild.id if guild else "Unknown"
    if guildName == "":
        guildName = "Unknown"

    return {
        "guildID": MakeNameSafe(guildID),
        "guildName": MakeNameSafe(guildName),
    }
def GetChannelInfoFromInteraction(
    interaction: discord.Interaction,
):
    channel = interaction.channel

    if type(channel) is discord.channel.DMChannel or type(channel) is discord.channel.GroupChannel:
        channelName = "DM with " + ", ".join([f"{recipient.global_name} ({recipient.name})" for recipient in channel.recipients if recipient != channel.me])
    else:
        channelName = channel.name if hasattr(channel, 'name') else "DM"

    channelID = channel.id

    return {
        "channelID": MakeNameSafe(channelID),
        "channelName": MakeNameSafe(channelName),
    }
def Timestamp() -> str:
    return MakeNameSafe(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

webhookSendDelaySeconds = 1
webhookBackoffSeconds = 30
webhookQueueMaxEmbeds = 1000
webhookMessageMaxEmbeds = 10
webhookMessageMaxChars = 6000
webhookQueues = {}
webhookBlockedUntil = {}
webhookDropped = 0

def FitEmbed(embedData: dict) -> dict:
    budget = 6000 - len(str(embedData.get("title", "")))
    fields = []
    for field in embedData.get("fields", [])[:25]:
        name = str(field.get("name", ""))[:256]
        value = str(field.get("value", ""))[:1024][:max(budget - len(name), 0)]
        budget -= len(name) + len(value)
        fields.append({
            **field,
            "name": name,
            "value": value,
        })
    return {
        **embedData,
        "fields": fields,
    }

async def SendToWebhooks(
    webhooksList: list[str],
    webhookUsername: str,
    embedData: dict,
):
    global webhookDropped
    if not webhooksList:
        return

    embedData = FitEmbed(embedData)
    size = len(str(embedData.get("title", ""))) + sum(len(field["name"]) + len(field["value"]) for field in embedData["fields"])
    for url in webhooksList:
        queue = webhookQueues.setdefault(url, collections.deque(maxlen=webhookQueueMaxEmbeds))
        if len(queue) == queue.maxlen:
            webhookDropped += 1
        queue.append((webhookUsername, embedData, size))

async def WebhookSenderLoop():
    global webhookDropped
    while True:
        await asyncio.sleep(webhookSendDelaySeconds)
        if webhookDropped:
            print(f"Dropped {webhookDropped} queued log embeds (webhook too slow or rate limited).")
            webhookDropped = 0
        await asyncio.gather(*(SendBatch(url, queue) for url, queue in list(webhookQueues.items())), return_exceptions=True)

async def SendBatch(webhookURL: str, queue: collections.deque):
    if not queue or webhookBlockedUntil.get(webhookURL, 0) > time.monotonic():
        return

    username = queue[0][0]
    batch, size = [], 0
    while queue and queue[0][0] == username and len(batch) < webhookMessageMaxEmbeds and (not batch or size + queue[0][2] <= webhookMessageMaxChars):
        batch.append(queue.popleft())
        size += batch[-1][2]

    retry = False
    try:
        session = await GetSharedSession()
        webhookData = {
            "embeds": [item[1] for item in batch],
            "username": username,
        }
        async with session.post(webhookURL, json=webhookData, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status == 429 or response.status >= 500:
                try:
                    backoff = float(response.headers.get("Retry-After", webhookBackoffSeconds))
                except ValueError:
                    backoff = webhookBackoffSeconds
                webhookBlockedUntil[webhookURL] = time.monotonic() + min(backoff, 3600)
                retry = True
            elif response.status != 204:
                print(f"Error sending to webhook: {response.status} - {await response.text()}")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        webhookBlockedUntil[webhookURL] = time.monotonic() + webhookBackoffSeconds
        retry = True
    except Exception as e:
        print(f"Error sending to webhook: {e}")
    if retry:
        queue.extendleft(reversed(batch))

def WriteToLogFile(
    filePath: str,
    logMessage: str,
):
    with open(filePath, "a", encoding="utf-8") as logFile:
        logFile.write(logMessage + "\n")

def SafeField(
    name: str,
    value: str,
    inline: bool = False,
):
    fields = []
    limit = 1024

    value = value if value else "-"
    chunks = [value[i:i+limit] for i in range(0, len(value), limit)]
    for chunk in chunks:
        fields.append({
            "name": name or "-",
            "value": chunk,
            "inline": inline,
        })

    return fields

def Header(title: str) -> dict:
    return {"name": f"__{title}__", "value": ""}

def Blank() -> dict:
    return {"name": "", "value": ""}

def UserFields(userInfo: dict) -> list[dict]:
    return [
        Header("User"),
        *SafeField("Username", userInfo['userDisplayName'], True),
        *SafeField("User Tag", userInfo['userName'], True),
        *SafeField("User ID", userInfo['userID'], True),
    ]

def InteractionFields(userInfo: dict, channelInfo: dict, guildInfo: dict, commandInfo: dict) -> list[dict]:
    return [
        *UserFields(userInfo),
        Blank(),
        Header("Channel"),
        *SafeField("Channel Name", channelInfo['channelName'], True),
        *SafeField("Channel ID", channelInfo['channelID'], True),
        Blank(),
        *SafeField("Guild Name", guildInfo['guildName'], True),
        *SafeField("Guild ID", guildInfo['guildID'], True),
        Blank(),
        Header("Command"),
        *SafeField("Command Name", commandInfo['commandName'], True),
        *SafeField("Command Options", str(commandInfo['commandOptions']), True),
        *SafeField("Copyable Command", commandInfo['copyableCommand']),
    ]

def ErrorFields(message, errorTraceback: str) -> list[dict]:
    return [
        Blank(),
        Header("Error"),
        *SafeField("Error Message", str(message)),
        *SafeField("Error Traceback", str(errorTraceback)[-3000:]),
        Blank(),
    ]

async def LogError(
    interaction: discord.Interaction,
    message,
):
    try:
        userInfo = GetUserInfoFromInteraction(interaction)
        guildInfo = await GetGuildInfoFromInteraction(interaction)
        channelInfo = GetChannelInfoFromInteraction(interaction)
        commandInfo = GetCommandInfoFromInteraction(interaction)
        errorTraceback = traceback.format_exc()

        fields = [
            *InteractionFields(userInfo, channelInfo, guildInfo, commandInfo),
            *ErrorFields(message, errorTraceback),
        ]

        embedData = {
            "title": f"Error With Command /{commandInfo['commandName']}",
            "color": Variables.defaultColorHex,
            "fields": fields,
        }

        logMessage = (
            f"[{Timestamp()}]"
            f"User: {userInfo}, "
            f"Guild: {guildInfo}, "
            f"Channel: {channelInfo}, "
            f"Command: {commandInfo}, "
            f"Error: {message}, "
            f"Traceback: {errorTraceback}"
        )

        print(logMessage)
        await asyncio.to_thread(WriteToLogFile, Variables.ERROR_LOG_FILE_PATH, logMessage)
        await SendToWebhooks(Variables.errorLogWebhooks, f"{Variables.defaultBotName} Error Logger", embedData)
    except Exception as e:
        print(f"Error logging error: {e}")

mainLoop = None
def SyncLogHeadlessError(message: str):
    if mainLoop is not None and mainLoop.is_running():
        asyncio.run_coroutine_threadsafe(LogHeadlessError(message), mainLoop)
        return
    print(f"Error: {message}")
    try:
        WriteToLogFile(Variables.ERROR_LOG_FILE_PATH, f"[{Timestamp()}]Error: {message}")
    except Exception:
        pass

async def LogHeadlessError(message: str):
    try:
        errorTraceback = traceback.format_exc()

        fields = ErrorFields(message, errorTraceback)

        embedData = {
            "title": "Runtime Error",
            "color": Variables.defaultColorHex,
            "fields": fields,
        }

        logMessage = (
            f"[{Timestamp()}]"
            f"Error: {message}, "
            f"Traceback: {errorTraceback}"
        )

        print(logMessage)
        await asyncio.to_thread(WriteToLogFile, Variables.ERROR_LOG_FILE_PATH, logMessage)
        await SendToWebhooks(Variables.errorLogWebhooks, f"{Variables.defaultBotName} Error Logger", embedData)
    except Exception as e:
        print(f"Error logging error: {e}")

async def LogCommandUsage(interaction: discord.Interaction):
    try:
        userInfo = GetUserInfoFromInteraction(interaction)
        guildInfo = await GetGuildInfoFromInteraction(interaction)
        channelInfo = GetChannelInfoFromInteraction(interaction)
        commandInfo = GetCommandInfoFromInteraction(interaction)

        embedData = {
            "title": f"{userInfo['userDisplayName']} Used Command /{commandInfo['commandName']}",
            "color": Variables.defaultColorHex,
            "fields": [
                *InteractionFields(userInfo, channelInfo, guildInfo, commandInfo),
                Blank(),
            ],
        }

        logMessage = (
            f"[{Timestamp()}] "
            f"User: {userInfo}, "
            f"Guild: {guildInfo}, "
            f"Channel: {channelInfo}, "
            f"Command: {commandInfo}"
        )

        await asyncio.to_thread(WriteToLogFile, Variables.COMMAND_LOG_FILE_PATH, logMessage)
        await SendToWebhooks(Variables.commandLogWebhooks, f"{Variables.defaultBotName} Command Logger", embedData)
    except Exception as e:
        print(f"Error logging command usage: {e}")
