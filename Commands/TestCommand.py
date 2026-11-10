import MainBot

import datetime
import discord

from Database import PersistentAppData
from Utils import Variables
from Utils import Logger

testCommandDescription = "Example bot command."

@MainBot.AppCommandWithAliases(
    MainBot.GetClient().tree,
    name="testcommand",
    aliases=[
        "testingcommand",
    ],
    description=testCommandDescription,
)
async def Command_Test(interaction: discord.Interaction):
    if await MainBot.isUserBlacklisted(interaction):
        return

    await interaction.response.defer(thinking=True, ephemeral=False)

    totalUptime = datetime.datetime.now() - MainBot.botStartTimestamp
    totalUptimeSeconds = int(totalUptime.total_seconds())
    uptimeDays, remainder = divmod(totalUptimeSeconds, 86400)
    uptimeHours, remainder = divmod(remainder, 3600)
    uptimeMinutes, seconds = divmod(remainder, 60)
    uptimeString = f"{uptimeDays}d {uptimeHours}h {uptimeMinutes}m {seconds}s"

    ping = round(MainBot.GetClient().latency * 1000)
    totalCommands = PersistentAppData.GetData("totalCommands", 0)

    embedDescription = (
        f"**Uptime:** {uptimeString}\n"
        f"**Ping:** {ping}ms\n"
        f"**Commands Used:** {totalCommands:,}\n"
        "\n"
        "**Info**\n"
        "This is an example command!."
    )

    embed = MainBot.CreateDefaultEmbed(
        createdAt=interaction.created_at,
        title="Bot Info",
        description=embedDescription,
        thumbnailLink=Variables.avatarLink,
        color=Variables.defaultDiscordColor,
    )

    await Logger.SendInteractionMessage(interaction=interaction, embed=embed, allowed_mentions=discord.AllowedMentions.none())
