import MainBot
import discord

from discord import app_commands

from Utils.Translation import Say, Text
from Game import Profiles
from Utils import Utils

class AdminGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="admin", description=Say(Text.ADMIN_GROUP_DESCRIPTION), guild_only=True)

adminGroup = AdminGroup()

async def RequireTarget(interaction: discord.Interaction, user: discord.Member) -> Utils.GuildID:
    guildID, _ = await Utils.RequireGuildAndMember(interaction.guild_id, user.id, interaction)
    await Profiles.EnsureProfile(guildID, user.id)
    return guildID
MainBot.GetClient().tree.add_command(adminGroup)
