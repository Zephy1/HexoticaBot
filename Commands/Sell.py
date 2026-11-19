import MainBot

import discord

from Utils.Translation import Say, Text
from Game import InventoryPanel
from Utils import Variables
from Game import Inventory
from Game import Selling
from Game import Trading
from Utils import Logger
from Utils import Utils
from Utils import Views
from Game import Items

class SellPanel(InventoryPanel.InventoryPanel):
    emptyText = Text.SELL_EMPTY

    def __init__(self, guildID: Utils.GuildID, userID: Utils.MemberID, filters: Inventory.InventoryFilter):
        super().__init__(guildID, userID, Text.SELL_EXPIRED, filters)
        self.confirming = False

    def Touch(self, interaction: discord.Interaction) -> None:
        super().Touch(interaction)
        self.confirming = False

    def Title(self) -> str:
        return Say(Text.SELL_TITLE)

    def SelectionLine(self, chosen: list[Inventory.InventoryItem]) -> str:
        if not chosen:
            return Say(Text.SELL_SELECTION_NONE)
        coins = Utils.CompactNumber(sum(item.value for item in chosen))
        if self.confirming:
            return Say(Text.SELL_CONFIRM_TITLE, count=len(chosen), s=Utils.PluralS(len(chosen)), coins=coins)
        return Say(Text.SELL_SELECTION, count=len(chosen), coins=coins) + self.HiddenNote(chosen)

    def ActionButtons(self, selectedCount: int) -> tuple[list[discord.ui.Button], discord.Color]:
        if self.confirming and selectedCount > 0:
            return [
                Views.Button(Say(Text.SELL_BUTTON_CONFIRM), self.OnConfirm, discord.ButtonStyle.danger),
                Views.Button(Say(Text.SELL_BUTTON_CANCEL), self.OnCancel),
            ], discord.Color.red()
        return [
            Views.Button(Say(Text.SELL_BUTTON_SELL, count=selectedCount), self.OnSell, discord.ButtonStyle.success, disabled=not selectedCount),
            *self.CommonButtons(selectedCount),
        ], Variables.defaultDiscordColor

    @Views.ButtonCallback
    async def OnSell(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.confirming = bool(self.selected)
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnCancel(self, interaction: discord.Interaction):
        self.Touch(interaction)
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnConfirm(self, interaction: discord.Interaction):
        self.Touch(interaction)
        itemIDs = sorted(self.selected, key=lambda itemID: Inventory.SortKey(self.sort, self.byID[itemID]))
        self.selected = set()
        if not itemIDs:
            await self.Show(interaction)
            return
        try:
            result = await Selling.SellItems(self.guildID, self.ownerID, itemIDs)
        except Exception:
            self.selected = set(itemIDs)
            raise
        if not result.sold:
            await self.Show(interaction, Say(Text.SELL_BULK_NONE))
            return
        message = Say(Text.SELL_BULK_DONE, count=len(result.sold), s=Utils.PluralS(len(result.sold)), coins=Utils.CompactNumber(result.coins))
        if result.skipped:
            message += Say(Text.SELL_BULK_SKIPPED, count=len(result.skipped), s=Utils.PluralS(len(result.skipped)))
        await self.Show(interaction)
        await Logger.SendInteractionMessage(interaction=interaction, message=message, ephemeral=True)

async def SellOne(interaction: discord.Interaction, guildID: Utils.GuildID, itemID: str) -> None:
    parsed = Items.ParseItemID(itemID)
    if parsed is None:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.GLOBAL_ITEM_ID_INVALID, itemID=itemID), ephemeral=True)
        return

    normalizedID = parsed.itemID
    if Trading.IsItemPending(guildID, normalizedID):
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.SELL_PENDING, itemID=normalizedID), ephemeral=True)
        return

    result = await Selling.SellItems(guildID, interaction.user.id, [normalizedID])
    message = Say(Text.SELL_DONE, itemID=normalizedID, coins=Utils.CompactNumber(result.coins)) if result.sold else Say(Text.SELL_NOT_OWNED, itemID=normalizedID)
    await Logger.SendInteractionMessage(interaction=interaction, message=message, ephemeral=True)

@MainBot.AppCommandWithAliases(
    MainBot.GetClient().tree,
    name="sell",
    description=Say(Text.SELL_DESCRIPTION),
    guildOnly=True,
    variableDescriptions={
        "itemID": Say(Text.GLOBAL_ITEM_ID),
        "armorType": Say(Text.SELL_ARMOR_TYPE),
        "pieceType": Say(Text.GLOBAL_PIECE_TYPE_DESCRIPTION),
    },
    autoComplete={
        "itemID": Items.AutocompleteOwnItems,
        "armorType": Items.AutocompleteArmorTypes,
        "pieceType": Items.AutocompleteArmorSlots,
    },
)
async def Command_Sell(
    interaction: discord.Interaction,
    itemID: str | None = None,
    armorType: str | None = None,
    pieceType: str | None = None,
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)

    if itemID:
        await SellOne(interaction, guildID, itemID)
        return

    filters = Inventory.InventoryFilter()
    if armorType:
        armor = Items.GetArmorType(armorType)
        if armor is None:
            await Utils.AbortCommand(interaction, Say(Text.SELL_ARMOR_TYPE_INVALID, armor=armorType))
        filters.armor = armor.value
    if pieceType:
        filters.slot = Inventory.ParseSlot(pieceType)
        if filters.slot is None:
            await Utils.AbortCommand(interaction, Say(Text.SELL_PIECE_INVALID, piece=pieceType))

    await SellPanel(guildID, interaction.user.id, filters).Start(interaction)
