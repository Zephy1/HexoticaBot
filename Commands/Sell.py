import MainBot

import functools
import discord
import asyncio
import math
import io

from Utils.Translation import Say, Text
from Utils import Variables
from Game import Profiles
from Game import SellCard
from Game import Selling
from Game import Trading
from Utils import Logger
from Utils import Utils
from Utils import Views
from Game import Items

class RarityModal(discord.ui.Modal):
    def __init__(self, panel: "SellPanel"):
        super().__init__(title=Say(Text.SELL_MODAL_TITLE))
        self.panel = panel
        filters = panel.filters
        self.low = discord.ui.TextInput(default="" if filters.minRarity is None else Items.FormatRarity(filters.minRarity), required=False, max_length=12)
        self.high = discord.ui.TextInput(default="" if filters.maxRarity is None else Items.FormatRarity(filters.maxRarity), required=False, max_length=12)
        self.add_item(discord.ui.Label(text=Say(Text.SELL_MODAL_MIN), description=Say(Text.SELL_MODAL_HINT), component=self.low))
        self.add_item(discord.ui.Label(text=Say(Text.SELL_MODAL_MAX), description=Say(Text.SELL_MODAL_HINT), component=self.high))

    @staticmethod
    def Parse(text: str) -> float | None:
        text = text.replace(",", "").strip()
        value = float(text) if text else None
        if value is not None and not math.isfinite(value):
            raise ValueError(text)
        return value

    @Views.ButtonCallback
    async def on_submit(self, interaction: discord.Interaction):
        self.panel.Touch(interaction)
        try:
            low, high = self.Parse(self.low.value), self.Parse(self.high.value)
        except ValueError:
            await self.panel.Show(interaction, Say(Text.SELL_MODAL_INVALID))
            return
        if low is not None and high is not None and low > high:
            low, high = high, low
        self.panel.filters.minRarity, self.panel.filters.maxRarity = low, high
        self.panel.page = 0
        await self.panel.Show(interaction)

class SellPanel(Views.Panel):
    def __init__(self, guildID: Utils.GuildID, userID: Utils.MemberID, filters: Selling.SellFilter):
        super().__init__(userID, Text.SELL_EXPIRED)
        self.guildID = guildID
        self.filters = filters
        self.sort = Selling.SortMode.RARITY_DESC
        self.page = 0
        self.pages = 1
        self.selected: set[Utils.ItemID] = set()
        self.confirming = False
        self.status = ""
        self.renders = 0
        self.items: list[Selling.SellItem] = []
        self.byID: dict[Utils.ItemID, Selling.SellItem] = {}
        self.visible: list[Selling.SellItem] = []

    async def Load(self) -> None:
        profile = Profiles.CachedProfile(Profiles.Scope(self.guildID, self.ownerID))
        if profile is None:
            profile = await Profiles.EnsureProfile(self.guildID, self.ownerID)
        self.items = await Selling.LoadItems(self.guildID, self.ownerID, profile)
        self.byID = {item.itemID: item for item in self.items}
        self.selected = {itemID for itemID in self.selected if itemID in self.byID and not self.byID[itemID].locked}
        self.visible = Selling.Arrange(self.items, self.filters, self.sort)
        self.pages = max(1, math.ceil(len(self.visible) / Selling.pageSize))
        self.page = min(self.page, self.pages - 1)

    def PageItems(self) -> list[Selling.SellItem]:
        start = self.page * Selling.pageSize
        return self.visible[start:start + Selling.pageSize]

    def Selectable(self, items: list[Selling.SellItem]) -> list[Utils.ItemID]:
        return [item.itemID for item in items if not item.locked]

    def Touch(self, interaction: discord.Interaction) -> None:
        super().Touch(interaction)
        self.confirming = False

    async def Compose(self) -> list[discord.File]:
        pageItems = self.PageItems()
        files: list[discord.File] = []
        imageName = ""
        if pageItems:
            png = await asyncio.to_thread(SellCard.Render, pageItems, self.selected)
            self.renders += 1
            imageName = f"sell{self.renders}.png"
            files.append(discord.File(io.BytesIO(png), filename=imageName))
        self.Build(pageItems, imageName)
        return files

    def Header(self) -> str:
        lines = [
            Say(Text.SELL_TITLE),
            Say(
                Text.SELL_STATS,
                page=self.page + 1,
                pages=self.pages,
                shown=len(self.visible),
                total=len(self.items),
                sort=Say(Selling.sortLabels[self.sort]),
            ),
        ]
        if self.filters.active:
            lines.append(Say(Text.SELL_FILTERS_LINE, filters=Say(Text.SELL_FILTER_SEPARATOR).join(self.filters.Describe())))
        return "\n".join(lines)

    def Summary(self) -> str:
        lines = []
        if self.status:
            lines.append(self.status)
        if not self.visible:
            lines.append(Say(Text.SELL_NO_MATCHES))
        chosen = [self.byID[itemID] for itemID in self.selected]
        if not chosen:
            lines.append(Say(Text.SELL_SELECTION_NONE))
            return "\n".join(lines)

        coins = Utils.FormatNumber(sum(item.value for item in chosen))
        if self.confirming:
            lines.append(self.ConfirmText(chosen, coins))
            return "\n".join(lines)

        line = Say(Text.SELL_SELECTION, count=len(chosen), coins=coins)
        visibleIDs = {item.itemID for item in self.visible}
        hidden = sum(1 for item in chosen if item.itemID not in visibleIDs)
        if hidden:
            line += Say(Text.SELL_SELECTION_HIDDEN, hidden=hidden)
        lines.append(line)
        return "\n".join(lines)

    def ConfirmText(self, chosen: list[Selling.SellItem], coins: str) -> str:
        count = len(chosen)
        return Say(Text.SELL_CONFIRM_TITLE, count=count, s=Utils.PluralS(count), coins=coins)

    def Alt(self, pageItems: list[Selling.SellItem]) -> str:
        return "; ".join(f"{item.name} #{item.hexCode} rarity {Items.FormatRarity(item.rarity)}" for item in pageItems)[:1000]

    def ItemSelect(self, pageItems: list[Selling.SellItem]) -> discord.ui.Select | None:
        options = [
            discord.SelectOption(
                label=Say(Text.SELL_OPTION_LABEL, name=item.name, hex=item.hexCode)[:100],
                value=item.itemID,
                description=Say(Text.SELL_OPTION_DESCRIPTION, rarity=Items.FormatRarity(item.rarity), coins=Utils.CompactNumber(item.value))[:100],
                emoji="\U0001F4CC" if item.showcased else None,
                default=item.itemID in self.selected,
            )
            for item in pageItems if not item.locked
        ]
        if not options:
            return None
        return Views.Dropdown(Say(Text.SELL_PLACEHOLDER_ITEMS), options, self.OnPick, min_values=0, max_values=len(options))

    def SortSelect(self) -> discord.ui.Select:
        options = [discord.SelectOption(label=Say(Selling.sortLabels[mode]), value=mode.value, default=mode is self.sort) for mode in Selling.SortMode]
        return Views.Dropdown(Say(Text.SELL_PLACEHOLDER_SORT), options, self.OnSort)

    def PieceSelect(self) -> discord.ui.Select:
        options = [discord.SelectOption(label=Say(Text.SELL_ALL_PIECES), value="all", default=self.filters.slot is None)]
        options += [
            discord.SelectOption(label=Selling.SlotLabel(slot.value), value=slot.value, default=self.filters.slot == slot.value)
            for slot in Utils.ArmorSlot
        ]
        return Views.Dropdown(Say(Text.SELL_PLACEHOLDER_PIECE), options, functools.partial(self.OnFilter, "slot"))

    def ArmorSelect(self) -> discord.ui.Select:
        counts = Selling.ArmorCounts(self.items)[:Selling.maxArmorOptions]
        if self.filters.armor is not None and self.filters.armor not in dict(counts):
            counts = [*counts[:Selling.maxArmorOptions - 1], (self.filters.armor, 0)]
        options = [discord.SelectOption(label=Say(Text.SELL_ALL_ARMOR), value="all", default=self.filters.armor is None)]
        options += [
            discord.SelectOption(
                label=Selling.ArmorLabel(armor)[:100],
                value=armor,
                description=Say(Text.SELL_ARMOR_OPTION_COUNT, count=count),
                default=self.filters.armor == armor,
            )
            for armor, count in counts
        ]
        return Views.Dropdown(Say(Text.SELL_PLACEHOLDER_ARMOR), options, functools.partial(self.OnFilter, "armor"))

    def Build(self, pageItems: list[Selling.SellItem], imageName: str) -> None:
        self.clear_items()
        selectedCount = len(self.selected)
        parts: list = [discord.ui.TextDisplay(self.Header())]
        if imageName:
            parts.append(discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{imageName}", description=self.Alt(pageItems))))
        parts.append(discord.ui.TextDisplay(self.Summary()))
        parts.append(discord.ui.Separator())

        itemSelect = self.ItemSelect(pageItems)
        if itemSelect is not None:
            parts.append(discord.ui.ActionRow(itemSelect))
        parts.append(discord.ui.ActionRow(self.SortSelect()))
        parts.append(discord.ui.ActionRow(self.PieceSelect()))
        parts.append(discord.ui.ActionRow(self.ArmorSelect()))

        selectableTotal = len(self.Selectable(self.visible))
        parts.append(discord.ui.ActionRow(
            Views.Button(Say(Text.SELL_BUTTON_PREV), functools.partial(self.OnPage, -1), disabled=self.page <= 0),
            Views.Button(Say(Text.SELL_BUTTON_PAGE, page=self.page + 1, pages=self.pages), disabled=True),
            Views.Button(Say(Text.SELL_BUTTON_NEXT), functools.partial(self.OnPage, 1), disabled=self.page >= self.pages - 1),
            Views.Button(Say(Text.SELL_BUTTON_SELECT_PAGE), self.OnSelectPage, disabled=not self.Selectable(pageItems)),
            Views.Button(Say(Text.SELL_BUTTON_SELECT_ALL, count=selectableTotal), self.OnSelectAll, disabled=not selectableTotal),
        ))

        confirming = self.confirming and selectedCount > 0
        if confirming:
            parts.append(discord.ui.ActionRow(
                Views.Button(Say(Text.SELL_BUTTON_CONFIRM), self.OnConfirm, discord.ButtonStyle.danger),
                Views.Button(Say(Text.SELL_BUTTON_CANCEL), self.OnCancel),
            ))
        else:
            parts.append(discord.ui.ActionRow(
                Views.Button(Say(Text.SELL_BUTTON_SELL, count=selectedCount), self.OnSell, discord.ButtonStyle.success, disabled=not selectedCount),
                Views.Button(Say(Text.SELL_BUTTON_CLEAR), self.OnClear, disabled=not selectedCount),
                Views.Button(Say(Text.SELL_BUTTON_RARITY), self.OnRarity),
                Views.Button(Say(Text.SELL_BUTTON_RESET), self.OnReset, disabled=not self.filters.active),
            ))

        color = discord.Color.red() if confirming else Variables.defaultDiscordColor
        self.add_item(discord.ui.Container(*parts, accent_color=color))

    async def Show(self, interaction: discord.Interaction, status: str = "") -> None:
        self.status = status
        await self.Load()
        files = await self.Compose()
        if not interaction.response.is_done():
            await interaction.response.defer()
        await interaction.edit_original_response(view=self, attachments=files)

    async def Start(self, interaction: discord.Interaction) -> None:
        self.lastInteraction = interaction
        await self.Load()
        if not self.items:
            await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.SELL_EMPTY), ephemeral=True)
            return
        files = await self.Compose()
        await interaction.followup.send(view=self, files=files, ephemeral=True)

    @Views.ButtonCallback
    async def OnPick(self, interaction: discord.Interaction):
        self.Touch(interaction)
        pageIDs = set(self.Selectable(self.PageItems()))
        picked = set(interaction.data.get("values", []))
        self.selected = (self.selected - pageIDs) | (picked & pageIDs)
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnSort(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.sort = Selling.SortMode(interaction.data["values"][0])
        self.page = 0
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnFilter(self, field: str, interaction: discord.Interaction):
        self.Touch(interaction)
        value = interaction.data["values"][0]
        setattr(self.filters, field, None if value == "all" else value)
        self.page = 0
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnPage(self, step: int, interaction: discord.Interaction):
        self.Touch(interaction)
        self.page = min(max(self.page + step, 0), self.pages - 1)
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnSelectPage(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.selected |= set(self.Selectable(self.PageItems()))
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnSelectAll(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.selected |= set(self.Selectable(self.visible))
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnClear(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.selected.clear()
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnReset(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.filters.Clear()
        self.page = 0
        await self.Show(interaction)

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
        itemIDs = sorted(self.selected, key=lambda itemID: Selling.SortKey(self.sort, self.byID[itemID]))
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
        message = Say(Text.SELL_BULK_DONE, count=len(result.sold), s=Utils.PluralS(len(result.sold)), coins=Utils.FormatNumber(result.coins))
        if result.skipped:
            message += Say(Text.SELL_BULK_SKIPPED, count=len(result.skipped), s=Utils.PluralS(len(result.skipped)))
        await self.Show(interaction)
        await Logger.SendInteractionMessage(interaction=interaction, message=message, ephemeral=True)

    async def OnRarity(self, interaction: discord.Interaction):
        await Views.OpenModal(interaction, RarityModal(self))

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
    message = Say(Text.SELL_DONE, itemID=normalizedID, coins=Utils.FormatNumber(result.coins)) if result.sold else Say(Text.SELL_NOT_OWNED, itemID=normalizedID)
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

    filters = Selling.SellFilter()
    if armorType:
        armor = Items.GetArmorType(armorType)
        if armor is None:
            await Utils.AbortCommand(interaction, Say(Text.SELL_ARMOR_TYPE_INVALID, armor=armorType))
        filters.armor = armor.value
    if pieceType:
        filters.slot = Selling.ParseSlot(pieceType)
        if filters.slot is None:
            await Utils.AbortCommand(interaction, Say(Text.SELL_PIECE_INVALID, piece=pieceType))

    await SellPanel(guildID, interaction.user.id, filters).Start(interaction)
