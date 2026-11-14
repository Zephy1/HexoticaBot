import MainBot

import discord

from Database import PersistentUserData
from Utils.Translation import Say, Text
from Commands.Admin import adminGroup
from Game import Profiles
from Utils import Logger
from Utils import Utils

@MainBot.AppCommandWithAliases(
    adminGroup,
    name="give_coins",
    description=Say(Text.ADMIN_GIVE_COINS_DESCRIPTION),
    variableDescriptions={
        "user": Say(Text.GLOBAL_USER),
        "amount": Say(Text.ADMIN_GIVE_COINS_AMOUNT),
    },
    permission="owner",
)
async def Command_AdminGiveCoins(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int,
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID, memberID = await Utils.RequireGuildAndMember(interaction.guild_id, user.id, interaction)
    await Profiles.EnsureProfile(guildID, user.id)

    profile = await PersistentUserData.ModifyUserData(
        Profiles.Scope(guildID, user.id), "profile",
        lambda p: {**p, "coins": max(0, p["coins"] + amount)},
    )
    await Logger.SendInteractionMessage(
        interaction=interaction,
        message=Say(Text.ADMIN_GIVE_COINS_GAVE, amount=Utils.FormatNumber(abs(amount)), userID=user.id, total=Utils.FormatNumber(profile['coins'])),
        ephemeral=True,
    )
