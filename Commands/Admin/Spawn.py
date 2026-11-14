import MainBot

import discord

from Utils.Translation import Say, Text
from Commands.Admin import adminGroup
from Utils import Logger
from Utils import Utils
from Game import Drops

@MainBot.AppCommandWithAliases(
    adminGroup,
    name="spawn",
    description=Say(Text.ADMIN_SPAWN_DESCRIPTION),
    variableDescriptions={
        "minRarity": Say(Text.ADMIN_SPAWN_MIN_RARITY),
        "maxRarity": Say(Text.ADMIN_SPAWN_MAX_RARITY),
    },
    permission="owner",
)
async def Command_AdminSpawn(
    interaction: discord.Interaction,
    minRarity: float | None = None,
    maxRarity: float | None = None,
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)
    channel = await Utils.RequireChannel(interaction)

    if minRarity is not None and maxRarity is not None and minRarity > maxRarity:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_SPAWN_BAD_RANGE), ephemeral=True)
        return

    rarityRange = (minRarity, maxRarity) if minRarity is not None or maxRarity is not None else None
    if await Drops.SpawnDrop(guildID, channel, rarityRange) is None:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_SPAWN_NOTHING_IN_RANGE if rarityRange is not None else Text.ADMIN_SPAWN_NOTHING), ephemeral=True)
        return

    await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_SPAWN_DONE), ephemeral=True)
