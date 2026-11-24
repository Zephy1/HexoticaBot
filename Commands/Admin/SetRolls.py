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
    name="set_rolls",
    description=Say(Text.ADMIN_SET_ROLLS_DESCRIPTION),
    variableDescriptions={
        "user": Say(Text.GLOBAL_USER),
        "amount": Say(Text.ADMIN_SET_ROLLS_AMOUNT),
    },
    permission=Utils.Permission.OWNER,
)
async def Command_AdminSetRolls(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int,
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID = await RequireTarget(interaction, user)

    await Atomic.ModifyUserData(
        Profiles.Scope(guildID, user.id), "profile",
        lambda p: {**p, "bonusRolls": max(0, amount)},
    )
    await Logger.Reply(interaction, Say(Text.ADMIN_SET_ROLLS_SET, userID=user.id, amount=max(0, amount), s=Utils.PluralS(max(0, amount))))
