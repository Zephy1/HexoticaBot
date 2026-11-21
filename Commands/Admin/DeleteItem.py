import MainBot

import discord

from Utils.Translation import Say, Text
from Commands.Admin import adminGroup
from Game import Selling
from Utils import Logger
from Utils import Utils
from Game import Items

@MainBot.AppCommandWithAliases(
    adminGroup,
    name="delete_item",
    description=Say(Text.ADMIN_DELETE_ITEM_DESCRIPTION),
    variableDescriptions={
        "user": Say(Text.GLOBAL_USER),
        "itemID": Say(Text.GLOBAL_ITEM_ID),
    },
    autoComplete={
        "itemID": Items.AutocompleteUserItems,
    },
    permission=Utils.Permission.OWNER,
)
async def Command_AdminDeleteItem(
    interaction: discord.Interaction,
    user: discord.Member,
    itemID: str,
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID, _ = await Utils.RequireGuildAndMember(interaction.guild_id, user.id, interaction)

    parsed = Items.ParseItemID(itemID)
    if parsed is None:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.GLOBAL_ITEM_ID_INVALID, itemID=itemID), ephemeral=True)
        return

    normalizedID = parsed.itemID
    result = await Selling.SellItems(guildID, user.id, [normalizedID], Selling.SellSource.ADMIN)
    if not result.sold:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_DELETE_ITEM_NOT_OWNED, userID=user.id, itemID=normalizedID), ephemeral=True)
        return

    await Logger.SendInteractionMessage(
        interaction=interaction,
        message=Say(Text.ADMIN_DELETE_ITEM_DONE, itemID=normalizedID, userID=user.id),
        ephemeral=True,
    )
