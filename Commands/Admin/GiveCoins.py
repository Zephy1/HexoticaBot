import MainBot

import discord

from Utils.Translation import Say, Text
from Commands.Admin import adminGroup, RequireTarget
from Database import Atomic
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
    permission=Utils.Permission.OWNER,
)
async def Command_AdminGiveCoins(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int,
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID = await RequireTarget(interaction, user)

    profile = await Atomic.ModifyUserData(
        Profiles.Scope(guildID, user.id), "profile",
        lambda p: {**p, "coins": max(0, p["coins"] + amount)},
    )
    await Logger.Reply(interaction, Say(Text.ADMIN_GIVE_COINS_GAVE, amount=Utils.CompactNumber(abs(amount)), userID=user.id, total=Utils.CompactNumber(profile['coins'])))
