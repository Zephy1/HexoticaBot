import MainBot

import discord

from Utils.Translation import Say, Text
from Game import InventoryPanel
from Utils import Variables
from Game import Inventory
from Game import Profiles
from Utils import Utils

class CollectionPanel(InventoryPanel.InventoryPanel):
    readOnly = True
    emptyText = Text.COLLECTION_EMPTY

    def __init__(self, guildID: Utils.GuildID, viewerID: Utils.MemberID, targetID: Utils.MemberID):
        super().__init__(guildID, viewerID, Text.COLLECTION_EXPIRED, inventoryID=targetID)

    def Title(self) -> str:
        return Say(Text.COLLECTION_TITLE, user=self.inventoryID)

    def SelectionLine(self, chosen: list[Inventory.InventoryItem]) -> str:
        return Say(Text.COLLECTION_VALUE, coins=Utils.CompactNumber(sum(item.value for item in self.items)))

    def ActionButtons(self, selectedCount: int) -> tuple[list[discord.ui.Button], discord.Color]:
        return self.SearchButtons(), Variables.defaultDiscordColor

@MainBot.AppCommandWithAliases(
    MainBot.GetClient().tree,
    name="collection",
    description=Say(Text.COLLECTION_DESCRIPTION),
    guildOnly=True,
    variableDescriptions={
        "user": Say(Text.COLLECTION_USER),
    },
)
async def Command_Collection(interaction: discord.Interaction, user: discord.Member | None = None):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)

    targetID = interaction.user.id if user is None else user.id
    if targetID != interaction.user.id and await Profiles.PeekProfile(guildID, targetID) is None:
        await Utils.AbortCommand(interaction, Say(Text.NO_PROFILE_USER))

    await CollectionPanel(guildID, interaction.user.id, targetID).Start(interaction)
