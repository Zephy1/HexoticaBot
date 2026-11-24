import MainBot

import discord

from Utils.Translation import Say, Text
from Game import Profiles
from Utils import Logger
from Utils import Utils
from Game import Drops

@MainBot.AppCommandWithAliases(
    MainBot.GetClient().tree,
    name="roll",
    description=Say(Text.ROLL_DESCRIPTION),
    guildOnly=True,
)
async def Command_Roll(interaction: discord.Interaction):
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)
    channelID = await Utils.RequireChannelID(interaction.channel_id, interaction)
    profile = await Profiles.PeekProfile(guildID, interaction.user.id)
    if profile is not None and Profiles.TotalRolls(profile) < 1:
        await Logger.Reply(interaction, Say(Text.ROLL_NO_ROLLS))
        return

    await interaction.response.defer(thinking=True)
    error = await Drops.RollDrop(guildID, interaction.user.id, channelID, interaction)
    if error is not None:
        await interaction.delete_original_response()
        await Logger.Reply(interaction, error)
