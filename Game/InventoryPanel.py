import functools
import discord
import asyncio
import math
import io

from Utils.Translation import Say, Text
from Game import InventoryCard
from Utils import Variables
from Game import Inventory
from Game import Profiles
from Utils import Logger
from Utils import Utils
from Utils import Views
from Game import Items

def Alt(items: list[Inventory.InventoryItem]) -> str:
    return "; ".join(f"{item.name} #{item.hexCode} rarity {Items.FormatRarity(item.rarity)}" for item in items)[:1000]

async def Gallery(
    items: list[Inventory.InventoryItem],
    selected: set[Utils.ItemID],
    filename: str,
    currentSlot: int | None = None,
) -> tuple[discord.File, discord.ui.MediaGallery]:
    png = await asyncio.to_thread(InventoryCard.Render, items, selected, currentSlot)
    return discord.File(io.BytesIO(png), filename=filename), discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{filename}", description=Alt(items)))

async def SidesGallery(
    left: list[Inventory.InventoryItem],
    right: list[Inventory.InventoryItem],
    labels: list[InventoryCard.SideLabel],
    name: str,
) -> tuple[list[discord.File], discord.ui.MediaGallery]:
    pngs = await asyncio.to_thread(InventoryCard.RenderSides, left, right, labels)
    filenames = [f"{name}-{number}.png" for number in range(2)]
    files = [discord.File(io.BytesIO(png), filename=filename) for png, filename in zip(pngs, filenames)]
    return files, discord.ui.MediaGallery(*(discord.MediaGalleryItem(f"attachment://{filename}", description=f"{label.title} {Alt(items)}".strip()[:1024]) for filename, items, label in zip(filenames, (left, right), labels)))

async def SendShowcase(interaction: discord.Interaction, guildID: Utils.GuildID, targetID: Utils.MemberID, ephemeral: bool = False) -> None:
    profile = await Profiles.PeekProfile(guildID, targetID)
    if profile is None:
        await Utils.AbortCommand(interaction, Say(Text.NO_PROFILE_USER))

    items = await Inventory.LoadItems(guildID, targetID, profile, set())
    sets = Inventory.ShowcaseSets(items, profile, guildID)
    if not sets:
        await Utils.AbortCommand(interaction, Say(Text.SHOWCASE_EMPTY_SELF if targetID == interaction.user.id else Text.SHOWCASE_EMPTY))

    png = await asyncio.to_thread(InventoryCard.RenderShowcase, sets)
    alt = Alt([piece for pieces, _ in sets for piece in pieces])
    await Logger.SendInteractionMessage(
        interaction=interaction,
        message=Say(Text.SHOWCASE_TITLE, user=targetID),
        discordFile=discord.File(io.BytesIO(png), filename="showcase.png", description=alt),
        ephemeral=ephemeral,
        allowed_mentions=discord.AllowedMentions.none(),
    )

def ParseNumber(text: str) -> float | None:
    text = text.replace(",", "").replace(" ", "")
    if not text:
        return None
    value = Utils.UncompactNumber(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value

class SearchModal(discord.ui.Modal):
    def __init__(self, panel: "InventoryPanel"):
        super().__init__(title=Say(Text.INVENTORY_BUTTON_SEARCH))
        self.panel = panel
        filters = panel.filters
        self.search = discord.ui.TextInput(default=filters.search, placeholder=Say(Text.INVENTORY_MODAL_SEARCH_HINT), required=False, max_length=100)
        self.low = discord.ui.TextInput(default="" if filters.minRarity is None else Items.FormatRarity(filters.minRarity), required=False, max_length=12)
        self.high = discord.ui.TextInput(default="" if filters.maxRarity is None else Items.FormatRarity(filters.maxRarity), required=False, max_length=12)
        self.add_item(discord.ui.Label(text=Say(Text.INVENTORY_MODAL_SEARCH), component=self.search))
        self.add_item(discord.ui.Label(text=Say(Text.INVENTORY_MODAL_MIN), description=Say(Text.INVENTORY_MODAL_HINT), component=self.low))
        self.add_item(discord.ui.Label(text=Say(Text.INVENTORY_MODAL_MAX), description=Say(Text.INVENTORY_MODAL_HINT), component=self.high))

    @Views.ButtonCallback
    async def on_submit(self, interaction: discord.Interaction):
        self.panel.Touch(interaction)
        try:
            low, high = ParseNumber(self.low.value), ParseNumber(self.high.value)
        except ValueError:
            await self.panel.Show(interaction, Say(Text.INVENTORY_MODAL_INVALID))
            return
        if low is not None and high is not None and low > high:
            low, high = high, low
        self.panel.filters.minRarity, self.panel.filters.maxRarity = low, high
        self.panel.filters.SetSearch(self.search.value)
        self.panel.page = 0
        await self.panel.Show(interaction)

class InventoryPanel(Views.Panel):
    allowEmpty = False
    emptyText = Text.INVENTORY_EMPTY
    maxSelected: int | None = None
    readOnly = False
    bulkSelect = True

    def __init__(
        self,
        guildID: Utils.GuildID,
        userID: Utils.MemberID,
        expiredText: Text,
        filters: Inventory.InventoryFilter | None = None,
        inventoryID: Utils.MemberID | None = None,
    ):
        super().__init__(userID, expiredText)
        self.guildID = guildID
        self.inventoryID = userID if inventoryID is None else inventoryID
        self.filters = Inventory.InventoryFilter() if filters is None else filters
        self.sort = Inventory.SortMode.RARITY_DESC
        self.page = 0
        self.pages = 1
        self.selected: set[Utils.ItemID] = set()
        self.status = ""
        self.renders = 0
        self.items: list[Inventory.InventoryItem] = []
        self.byID: dict[Utils.ItemID, Inventory.InventoryItem] = {}
        self.visible: list[Inventory.InventoryItem] = []

    async def FetchItems(self) -> list[Inventory.InventoryItem]:
        profile = Profiles.CachedProfile(Profiles.Scope(self.guildID, self.inventoryID))
        if profile is None:
            profile = await Profiles.EnsureProfile(self.guildID, self.inventoryID)
        return await Inventory.LoadItems(self.guildID, self.inventoryID, profile, self.Pending())

    async def Load(self) -> None:
        self.items = await self.FetchItems()
        self.byID = {item.itemID: item for item in self.items}
        self.selected = {itemID for itemID in self.selected if itemID in self.byID and not self.byID[itemID].locked}
        self.Conform()
        if self.maxSelected is not None and len(self.selected) > self.maxSelected:
            keep = sorted(self.selected, key=lambda itemID: Inventory.SortKey(self.sort, self.byID[itemID]))
            self.selected = set(keep[:self.maxSelected])
            self.status = Say(Text.INVENTORY_LIMIT, limit=self.maxSelected)
        self.visible = self.Visible()
        self.pages = max(1, math.ceil(len(self.visible) / Inventory.pageSize))
        self.page = min(self.page, self.pages - 1)

    def Conform(self) -> None:
        pass

    def Visible(self) -> list[Inventory.InventoryItem]:
        return Inventory.Arrange(self.items, self.filters, self.sort)

    def HeaderRows(self) -> list[discord.ui.ActionRow]:
        return []

    async def Preview(self) -> tuple[discord.File, discord.ui.MediaGallery] | None:
        return None

    def CurrentSlot(self) -> int | None:
        return None

    def Pending(self) -> set[Utils.ItemID] | None:
        return None

    def PageItems(self) -> list[Inventory.InventoryItem]:
        start = self.page * Inventory.pageSize
        return self.visible[start:start + Inventory.pageSize]

    def Selectable(self, items: list[Inventory.InventoryItem]) -> list[Utils.ItemID]:
        return [item.itemID for item in items if not item.locked]

    def Title(self) -> str:
        return Say(Text.INVENTORY_TITLE)

    def Header(self) -> str:
        lines = [
            self.Title(),
            Say(
                Text.INVENTORY_STATS,
                page=self.page + 1,
                pages=self.pages,
                shown=len(self.visible),
                total=len(self.items),
                sort=Say(Inventory.sortLabels[self.sort]),
            ),
        ]
        if self.filters.active:
            lines.append(Say(Text.INVENTORY_FILTERS_LINE, filters=Say(Text.INVENTORY_FILTER_SEPARATOR).join(self.filters.Describe())))
        return "\n".join(lines)

    def Summary(self) -> str:
        lines = [self.status] if self.status else []
        if not self.items:
            lines.append(Say(self.emptyText))
        elif not self.visible:
            lines.append(Say(Text.INVENTORY_NO_MATCHES))
        selection = self.SelectionLine([self.byID[itemID] for itemID in self.selected])
        if selection:
            lines.append(selection)
        return "\n".join(lines)

    def SelectionLine(self, chosen: list[Inventory.InventoryItem]) -> str:
        return Say(Text.INVENTORY_SELECTION, count=len(chosen)) + self.HiddenNote(chosen)

    def HiddenNote(self, chosen: list[Inventory.InventoryItem]) -> str:
        visibleIDs = {item.itemID for item in self.visible}
        hidden = sum(1 for item in chosen if item.itemID not in visibleIDs)
        return Say(Text.INVENTORY_SELECTION_HIDDEN, hidden=hidden) if hidden else ""

    def SearchButtons(self) -> list[discord.ui.Button]:
        return [
            Views.Button(Say(Text.INVENTORY_BUTTON_SEARCH), self.OnSearch),
            Views.Button(Say(Text.INVENTORY_BUTTON_RESET), self.OnReset, disabled=not self.filters.active),
        ]

    def CommonButtons(self, selectedCount: int) -> list[discord.ui.Button]:
        return [Views.Button(Say(Text.INVENTORY_BUTTON_CLEAR), self.OnClear, disabled=not selectedCount), *self.SearchButtons()]

    def ActionButtons(self, selectedCount: int) -> tuple[list[discord.ui.Button], discord.Color]:
        return self.CommonButtons(selectedCount), Variables.defaultDiscordColor

    def ItemSelect(self, pageItems: list[Inventory.InventoryItem]) -> discord.ui.Select | None:
        options = [
            discord.SelectOption(
                label=Say(Text.INVENTORY_OPTION_LABEL, name=item.name, hex=item.hexCode)[:100],
                value=item.itemID,
                description=Say(Text.INVENTORY_OPTION_DESCRIPTION, rarity=Items.FormatRarity(item.rarity), coins=Utils.CompactNumber(item.value))[:100],
                emoji="\U0001F4CC" if item.showcased else None,
                default=item.itemID in self.selected,
            )
            for item in pageItems if not item.locked
        ]
        if not options:
            return None
        return Views.Dropdown(Say(Text.INVENTORY_PLACEHOLDER_ITEMS), options, self.OnPick, min_values=0, max_values=len(options))

    def SortSelect(self) -> discord.ui.Select:
        options = [discord.SelectOption(label=Say(Inventory.sortLabels[mode]), value=mode.value, default=mode is self.sort) for mode in Inventory.SortMode]
        return Views.Dropdown(Say(Text.INVENTORY_PLACEHOLDER_SORT), options, self.OnSort)

    def PieceSelect(self) -> discord.ui.Select:
        options = [discord.SelectOption(label=Say(Text.INVENTORY_ALL_PIECES), value="all", default=self.filters.slot is None)]
        options += [
            discord.SelectOption(label=Inventory.SlotLabel(slot.value), value=slot.value, default=self.filters.slot == slot.value)
            for slot in Utils.ArmorSlot
        ]
        return Views.Dropdown(Say(Text.INVENTORY_PLACEHOLDER_PIECE), options, functools.partial(self.OnFilter, "slot"))

    def ArmorSelect(self) -> discord.ui.Select:
        owned = dict(Inventory.ArmorCounts(self.items))
        counts = list(owned.items())[:Inventory.maxArmorOptions]
        active = self.filters.armor
        if active in owned and (active, owned[active]) not in counts:
            counts = [*counts[:Inventory.maxArmorOptions - 1], (active, owned[active])]
        options = [discord.SelectOption(label=Say(Text.INVENTORY_ALL_ARMOR), value="all", default=self.filters.armor is None)]
        options += [
            discord.SelectOption(
                label=Inventory.ArmorLabel(armor)[:100],
                value=armor,
                description=Say(Text.INVENTORY_ARMOR_OPTION_COUNT, count=count),
                default=self.filters.armor == armor,
            )
            for armor, count in counts
        ]
        return Views.Dropdown(Say(Text.INVENTORY_PLACEHOLDER_ARMOR), options, functools.partial(self.OnFilter, "armor"))

    def Build(self, pageItems: list[Inventory.InventoryItem], gallery: discord.ui.MediaGallery | None, preview: discord.ui.MediaGallery | None = None) -> None:
        self.clear_items()
        selectedCount = len(self.selected)
        parts: list = [discord.ui.TextDisplay(self.Header())]
        if gallery is not None:
            parts.append(gallery)
        summary = self.Summary()
        if summary:
            parts.append(discord.ui.TextDisplay(summary))
        if preview is not None:
            parts.append(preview)
        parts.append(discord.ui.Separator())

        parts.extend(self.HeaderRows())
        itemSelect = None if self.readOnly else self.ItemSelect(pageItems)
        if itemSelect is not None:
            parts.append(discord.ui.ActionRow(itemSelect))
        parts.append(discord.ui.ActionRow(self.SortSelect()))
        parts.append(discord.ui.ActionRow(self.PieceSelect()))
        parts.append(discord.ui.ActionRow(self.ArmorSelect()))

        selectableTotal = len(self.Selectable(self.visible))
        pager = [
            Views.Button(Say(Text.INVENTORY_BUTTON_PREV), functools.partial(self.OnPage, -1), disabled=self.page <= 0),
            Views.Button(Say(Text.INVENTORY_BUTTON_PAGE, page=self.page + 1, pages=self.pages), disabled=True),
            Views.Button(Say(Text.INVENTORY_BUTTON_NEXT), functools.partial(self.OnPage, 1), disabled=self.page >= self.pages - 1),
        ]
        if not self.readOnly and self.bulkSelect:
            pager += [
                Views.Button(Say(Text.INVENTORY_BUTTON_SELECT_PAGE), self.OnSelectPage, disabled=not self.Selectable(pageItems)),
                Views.Button(Say(Text.INVENTORY_BUTTON_SELECT_ALL, count=selectableTotal), self.OnSelectAll, disabled=not selectableTotal),
            ]
        parts.append(discord.ui.ActionRow(*pager))

        buttons, color = self.ActionButtons(selectedCount)
        parts.append(discord.ui.ActionRow(*buttons))
        self.add_item(discord.ui.Container(*parts, accent_color=color))

    async def Compose(self) -> list[discord.File]:
        pageItems = self.PageItems()
        files: list[discord.File] = []
        gallery = None
        if pageItems:
            self.renders += 1
            file, gallery = await Gallery(pageItems, self.selected, f"inventory{self.renders}.png", self.CurrentSlot())
            files.append(file)
        preview = await self.Preview()
        if preview is not None:
            files.append(preview[0])
        self.Build(pageItems, gallery, None if preview is None else preview[1])
        return files

    async def Show(self, interaction: discord.Interaction, status: str = "") -> None:
        self.status = status
        await self.Load()
        if not interaction.response.is_done():
            await interaction.response.defer()

        async def push():
            files = await self.Compose()
            await interaction.edit_original_response(view=self, attachments=files)

        await Views.Retry(push)

    async def Start(self, interaction: discord.Interaction) -> None:
        self.lastInteraction = interaction
        await self.Load()
        if not self.items and not self.allowEmpty:
            await Logger.Reply(interaction, Say(self.emptyText))
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
        self.sort = Inventory.SortMode(interaction.data["values"][0])
        self.page = 0
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnFilter(self, field: str, interaction: discord.Interaction):
        self.Touch(interaction)
        self.SetFilter(field, interaction.data["values"][0])
        self.page = 0
        await self.Show(interaction)

    def SetFilter(self, field: str, value: str) -> None:
        setattr(self.filters, field, None if value == "all" else value)
        if self.filters.slot is not None and Utils.ArmorSlot(self.filters.slot) not in Items.ArmorSlots(self.filters.armor):
            self.filters.slot = None

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

    async def OnSearch(self, interaction: discord.Interaction):
        await Views.OpenModal(interaction, SearchModal(self))
