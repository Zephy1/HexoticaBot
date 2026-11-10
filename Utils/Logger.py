import collections
import traceback
import datetime
import aiohttp
import asyncio
import discord
import time

from Utils import Variables

def MakeNameSafe(name):
    if name is None:
        return f"Unknown"
    if type(name) == str:
        name = name.encode('ascii', 'replace').decode('ascii')
    return str(name).replace("_", "\\_")

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
    if embed is None and message is None:
        message = "Error: No message or embed provided."

    try:
        if not interaction.response.is_done():
            return await interaction.response.send_message(content=message, embed=embed, file=discordFile, files=discordFiles, ephemeral=ephemeral, view=view, allowed_mentions=allowed_mentions)
        else:
            return await interaction.followup.send(content=message, embed=embed, file=discordFile, files=discordFiles, ephemeral=ephemeral, view=view, allowed_mentions=allowed_mentions, wait=True)
    except Exception as e:
        await LogError(interaction, interaction.client, f"Error sending interaction message: {e}")
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
        await LogError(interaction, interaction.client, f"Error editing interaction message: {e}")

async def LogInteractionError(
    interaction: discord.Interaction,
    client: discord.client,
    message: str,
):
    await SendInteractionMessage(interaction, message="Something went wrong. The error has been logged.", ephemeral=True)
    await LogError(interaction, client, message)

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
_guildNames = {}
async def GetGuildInfoFromInteraction(
    interaction: discord.Interaction,
    client: discord.Client,
):
    guild = interaction.guild
    guildName = "DM"
    if guild:
        cached = _guildNames.get(guild.id)
        if cached is None or cached[0] < time.monotonic():
            try:
                name = (await client.fetch_guild_preview(guild.id)).name
            except Exception:
                name = None
            cached = _guildNames[guild.id] = (time.monotonic() + (guildNameTtlSeconds if name else guildNameFailTtlSeconds), name)
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
def GetTimestampInfo():
    timestamp = time.time()
    now = datetime.datetime.now()
    timestampString = now.strftime("%Y-%m-%d %H:%M:%S")
    timestampISO = now.isoformat()

    return {
        "timestamp": MakeNameSafe(timestamp),
        "timestampString": MakeNameSafe(timestampString),
        "timestampISO": MakeNameSafe(timestampISO),
    }

webhookSendDelaySeconds = 1
webhookBackoffSeconds = 30
webhookQueueMaxEmbeds = 1000
webhookMessageMaxEmbeds = 10
webhookMessageMaxChars = 6000
_webhookQueues = {}
_webhookBlockedUntil = {}
_webhookDropped = 0

def _FitEmbed(embedData: dict) -> dict:
    budget = 6000 - len(str(embedData.get("title", "")))
    fields = []
    for field in embedData.get("fields", [])[:25]:
        name = str(field.get("name", ""))[:256]
        value = str(field.get("value", ""))[:1024][:max(budget - len(name), 0)]
        budget -= len(name) + len(value)
        fields.append({**field, "name": name, "value": value})
    return {**embedData, "fields": fields}

async def SendToWebhooks(
    webhooksList: list[str],
    webhookUsername: str,
    embedData: dict,
):
    global _webhookDropped
    if not webhooksList:
        return

    embedData = _FitEmbed(embedData)
    size = len(str(embedData.get("title", ""))) + sum(len(field["name"]) + len(field["value"]) for field in embedData["fields"])
    for url in webhooksList:
        queue = _webhookQueues.setdefault(url, collections.deque(maxlen=webhookQueueMaxEmbeds))
        if len(queue) == queue.maxlen:
            _webhookDropped += 1
        queue.append((webhookUsername, embedData, size))

async def WebhookSenderLoop():
    global _webhookDropped
    while True:
        await asyncio.sleep(webhookSendDelaySeconds)
        if _webhookDropped:
            print(f"Dropped {_webhookDropped} queued log embeds (webhook too slow or rate limited).")
            _webhookDropped = 0
        await asyncio.gather(*(_SendBatch(url, queue) for url, queue in list(_webhookQueues.items())), return_exceptions=True)

async def _SendBatch(webhookURL: str, queue: collections.deque):
    if not queue or _webhookBlockedUntil.get(webhookURL, 0) > time.monotonic():
        return

    username = queue[0][0]
    batch, size = [], 0
    while queue and queue[0][0] == username and len(batch) < webhookMessageMaxEmbeds and (not batch or size + queue[0][2] <= webhookMessageMaxChars):
        batch.append(queue.popleft())
        size += batch[-1][2]

    retry = False
    try:
        session = await Utils.GetSharedSession()
        webhookData = {"embeds": [item[1] for item in batch], "username": username}
        async with session.post(webhookURL, json=webhookData, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status == 429 or response.status >= 500:
                try:
                    backoff = float(response.headers.get("Retry-After", webhookBackoffSeconds))
                except ValueError:
                    backoff = webhookBackoffSeconds
                _webhookBlockedUntil[webhookURL] = time.monotonic() + min(backoff, 3600)
                retry = True
            elif response.status != 204:
                print(f"Error sending to webhook: {response.status} - {await response.text()}")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        _webhookBlockedUntil[webhookURL] = time.monotonic() + webhookBackoffSeconds
        retry = True
    except Exception as e:
        print(f"Error sending to webhook: {e}")
    if retry:
        queue.extendleft(reversed(batch))

def WriteToLogFile(
    filePath: str,
    logMessage: str,
):
    with open(filePath, "a") as logFile:
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
    for i, chunk in enumerate(chunks):
        fields.append({"name": name or "-", "value": chunk, "inline": inline})

    return fields

async def LogError(
    interaction: discord.Interaction,
    client,
    message,
):
    try:
        userInfo = GetUserInfoFromInteraction(interaction)
        guildInfo = await GetGuildInfoFromInteraction(interaction, client)
        channelInfo = GetChannelInfoFromInteraction(interaction)
        commandInfo = GetCommandInfoFromInteraction(interaction)
        timestampInfo = GetTimestampInfo()
        errorTraceback = traceback.format_exc()

        fields = [
            {"name": "__User__", "value": ""},
            {"name": "Username", "value": userInfo['userDisplayName'], "inline": True},
            {"name": "User Tag", "value": userInfo['userName'], "inline": True},
            {"name": "User ID", "value": userInfo['userID'], "inline": True},
            {"name": "", "value": ""},
            {"name": "__Channel__", "value": ""},
            {"name": "Channel Name", "value": channelInfo['channelName'], "inline": True},
            {"name": "Channel ID", "value": channelInfo['channelID'], "inline": True},
            {"name": "", "value": ""},
            {"name": "Guild Name", "value": guildInfo['guildName'], "inline": True},
            {"name": "Guild ID", "value": guildInfo['guildID'], "inline": True},
            {"name": "", "value": ""},
            {"name": "__Command__", "value": ""},
        ]
        fields.extend(SafeField("Command Name", commandInfo['commandName'], True))
        fields.extend(SafeField("Command Options", str(commandInfo['commandOptions']), True))
        fields.extend(SafeField("Copyable Command", commandInfo['copyableCommand']))
        fields.extend([
            {"name": "", "value": ""},
            {"name": "__Error__", "value": ""},
        ])
        fields.extend(SafeField("Error Message", str(message)))
        fields.extend(SafeField("Error Traceback", str(errorTraceback)[-3000:]))
        fields.extend([
            {"name": "", "value": ""}
        ])

        embedData = {
            "title": f"Error With Command /{commandInfo['commandName']}",
            "color": Variables.defaultColorHex,
            "fields": fields,
        }

        logMessage = (
            f"[{timestampInfo['timestampString']}]"
            f"User: {userInfo}, "
            f"Guild: {guildInfo}, "
            f"Channel: {channelInfo}, "
            f"Command: {commandInfo}, "
            f"Error: {message}, "
            f"Traceback: {errorTraceback}"
        )

        WriteToLogFile(Variables.ERROR_LOG_FILE_PATH, logMessage)
        await asyncio.gather(
            SendToWebhooks(Variables.errorLogWebhooks, f"{Variables.defaultBotName} Error Logger", embedData)
        )
    except Exception as e:
        print(f"Error logging error: {e}")

mainLoop = None
def SyncLogHeadlessError(message: str):
    if mainLoop is not None and mainLoop.is_running():
        asyncio.run_coroutine_threadsafe(LogHeadlessError(message), mainLoop)
        return
    try:
        WriteToLogFile(Variables.ERROR_LOG_FILE_PATH, f"[{GetTimestampInfo()['timestampString']}]Error: {message}")
    except Exception:
        print(f"Error: {message}")

async def LogHeadlessError(message: str):
    try:
        timestampInfo = GetTimestampInfo()
        errorTraceback = traceback.format_exc()

        fields = [
            {"name": "", "value": ""},
            {"name": "__Error__", "value": ""},
        ]
        fields.extend(SafeField("Error Message", str(message)))
        fields.extend(SafeField("Error Traceback", str(errorTraceback)[-3000:]))
        fields.extend([
            {"name": "", "value": ""}
        ])

        embedData = {
            "title": f"Runtime Error",
            "color": Variables.defaultColorHex,
            "fields": fields,
        }

        logMessage = (
            f"[{timestampInfo['timestampString']}]"
            f"Error: {message}, "
            f"Traceback: {errorTraceback}"
        )

        WriteToLogFile(Variables.ERROR_LOG_FILE_PATH, logMessage)
        await asyncio.gather(
            SendToWebhooks(Variables.errorLogWebhooks, f"{Variables.defaultBotName} Error Logger", embedData)
        )
    except Exception as e:
        print(f"Error logging error: {e}")

async def LogCommandUsage(
    interaction: discord.Interaction,
    client: discord.Client,
):
    try:
        userInfo = GetUserInfoFromInteraction(interaction)
        guildInfo = await GetGuildInfoFromInteraction(interaction=interaction, client=client)
        channelInfo = GetChannelInfoFromInteraction(interaction)
        commandInfo = GetCommandInfoFromInteraction(interaction)
        timestampInfo = GetTimestampInfo()

        embedData = {
            "title": f"{userInfo['userDisplayName']} Used Command /{commandInfo['commandName']}",
            "color": Variables.defaultColorHex,
            "fields": [
                {"name": "__User__", "value": ""},
                {"name": "Username", "value": userInfo['userDisplayName'], "inline": True},
                {"name": "User Tag", "value": userInfo['userName'], "inline": True},
                {"name": "User ID", "value": userInfo['userID'], "inline": True},
                {"name": "", "value": ""},
                {"name": "__Channel__", "value": ""},
                {"name": "Channel Name", "value": channelInfo['channelName'], "inline": True},
                {"name": "Channel ID", "value": channelInfo['channelID'], "inline": True},
                {"name": "", "value": ""},
                {"name": "Guild Name", "value": guildInfo['guildName'], "inline": True},
                {"name": "Guild ID", "value": guildInfo['guildID'], "inline": True},
                {"name": "", "value": ""},
                {"name": "__Command__", "value": ""},
                {"name": "Command Name", "value": commandInfo['commandName'], "inline": True},
                {"name": "Command Options", "value": str(commandInfo['commandOptions']), "inline": True},
                {"name": "Copyable Command", "value": commandInfo['copyableCommand']},
                {"name": "", "value": ""},
            ],
        }

        logMessage = (
            f"[{timestampInfo['timestampString']}] "
            f"User: {userInfo}, "
            f"Guild: {guildInfo}, "
            f"Channel: {channelInfo}, "
            f"Command: {commandInfo}"
        )

        WriteToLogFile(Variables.COMMAND_LOG_FILE_PATH, logMessage)
        await asyncio.gather(
            SendToWebhooks(Variables.commandLogWebhooks, f"{Variables.defaultBotName} Command Logger", embedData)
        )
    except Exception as e:
        print(f"Error logging command usage: {e}")

async def LogRequest(
    interaction: discord.Interaction,
    requestData: dict,
):
    userInfo = GetUserInfoFromInteraction(interaction)
    timestampInfo = GetTimestampInfo()
    requestType = requestData.get("requestType", "Unknown")

    embedData = {
        "title": f"{userInfo['userDisplayName']} Submitted {requestType} Request",
        "color": Variables.defaultColorHex,
        "fields": [
            {"name": "__User__", "value": ""},
            {"name": "Username", "value": userInfo['userDisplayName'], "inline": True},
            {"name": "User Tag", "value": userInfo['userName'], "inline": True},
            {"name": "User ID", "value": userInfo['userID'], "inline": True},
            {"name": "", "value": ""},
            {"name": "__Request__", "value": ""},
            {"name": "Request Type", "value": requestType, "inline": True},
            {"name": "Request Data", "value": str(requestData), "inline": True},
            {"name": "", "value": ""},
        ],
    }

    logMessage = (
        f"[{timestampInfo['timestampString']}] "
        f"User: {userInfo}, "
        f"Request: {requestData}"
    )

    WriteToLogFile(Variables.REQUESTS_LOG_FILE_PATH, logMessage)
    await asyncio.gather(
        SendToWebhooks(Variables.requestsLogWebhooks, f"{Variables.defaultBotName} Request Logger", embedData)
    )
