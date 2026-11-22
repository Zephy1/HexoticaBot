import MainBot

import functools
import discord
import asyncio
import io

from discord import app_commands

from Utils.Translation import Say, Text
from Game import InventoryPanel
from Game import InventoryCard
from Utils import Variables
from Game import Inventory
from Game import Profiles
from Utils import Logger
from Utils import Utils
from Utils import Views

showcaseGroup = app_commands.Group(name="showcase", description=Say(Text.SHOWCASE_GROUP_DESCRIPTION), guild_only=True)
MainBot.GetClient().tree.add_command(showcaseGroup)

slotsPerMenu = 25

def PieceOrder(item: Inventory.InventoryItem) -> int:
    return Inventory.slotOrder.get(item.slot, len(Inventory.slotOrder))

class ShowcasePanel(InventoryPanel.InventoryPanel):
    maxSelected = len(Utils.ArmorSlot)
    bulkSelect = False

    def __init__(self, guildID: Utils.GuildID, userID: Utils.MemberID, profile: dict):
        super().__init__(guildID, userID, Text.SHOWCASE_EXPIRED)
        self.slotCount = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.STARTING_SHOWCASE_SLOTS)
        self.capacity = Profiles.EarningCapacity(profile, guildID)
        self.saved = {int(slot): list(itemIDs) for slot, itemIDs in profile["showcase"].items()}
        self.savedEarning = Profiles.ActiveSlots(profile, guildID)
        self.assign = {itemID: slot for slot, itemIDs in self.saved.items() for itemID in itemIDs}
        self.earn = list(self.savedEarning)
        self.known: set[Utils.ItemID] = set()
        self.confirming = False
        self.previewKey: tuple = ()
        self.previewPNG = b""
        self.previewVersion = 0
        self.GoTo(next((number for number in range(1, self.slotCount + 1) if number not in self.saved), 1))

    def Assigned(self, slot: Utils.SlotIndex) -> set[Utils.ItemID]:
        return {itemID for itemID, number in self.assign.items() if number == slot}

    def Layout(self) -> dict[Utils.SlotIndex, list[Utils.ItemID]]:
        layout: dict[Utils.SlotIndex, list[Utils.ItemID]] = {}
        for itemID, slot in self.assign.items():
            layout.setdefault(slot, []).append(itemID)
        return {slot: sorted(itemIDs, key=lambda itemID: PieceOrder(self.byID[itemID])) for slot, itemIDs in layout.items()}

    def Touch(self, interaction: discord.Interaction) -> None:
        super().Touch(interaction)
        self.confirming = False

    def CurrentSlot(self) -> int | None:
        return self.slot

    async def Load(self) -> None:
        await super().Load()
        if not self.Changes():
            return
        layout, earning = self.Layout(), list(self.earn)
        try:
            await Profiles.EditShowcase(self.guildID, self.ownerID, lambda profile: Profiles.SetShowcase(profile, self.guildID, self.ownerID, layout, earning))
        except ValueError as error:
            self.assign = {itemID: slot for slot, itemIDs in self.saved.items() for itemID in itemIDs}
            self.earn = list(self.savedEarning)
            self.GoTo(self.slot)
            await super().Load()
            self.status = str(error)
            return
        self.saved, self.savedEarning = layout, earning
        await super().Load()

    def Changes(self) -> int:
        layout = self.Layout()
        slots = {slot for slot in layout.keys() | self.saved.keys() if set(layout.get(slot, ())) != set(self.saved.get(slot, ()))}
        return len(slots | (set(self.earn) ^ set(self.savedEarning)))

    def GoTo(self, slot: Utils.SlotIndex) -> None:
        self.slot = min(max(slot, 1), self.slotCount)
        self.selected = self.Assigned(self.slot)
        self.known = set()
        self.filters.armor = None
        self.page = 0

    def Conform(self) -> None:
        self.assign = {itemID: slot for itemID, slot in self.assign.items() if itemID in self.byID}
        had = bool(self.Assigned(self.slot))
        fresh = self.selected - self.known
        chosen = sorted((self.byID[itemID] for itemID in self.selected), key=lambda item: (item.itemID not in fresh, Inventory.SortKey(self.sort, item)))
        armor = self.filters.armor or (chosen[0].armor if chosen else None)
        allowed = Utils.THREE_PIECE if armor in Utils.THREE_PIECE else {armor}
        kept: dict[str, Inventory.InventoryItem] = {}
        for item in chosen:
            if item.armor in allowed:
                kept.setdefault(item.slot, item)
        for itemID in self.Assigned(self.slot):
            del self.assign[itemID]
        for item in kept.values():
            self.assign[item.itemID] = self.slot
        self.selected = {item.itemID for item in kept.values()}
        self.known = set(self.selected)
        if kept:
            self.filters.armor = None if armor in Utils.THREE_PIECE else armor
        elif had:
            self.filters.armor = None
        filled = set(self.assign.values())
        self.earn = [slot for slot in self.earn if slot in filled]
        if kept and not had and len(self.earn) < self.capacity:
            self.earn.append(self.slot)

    def Visible(self) -> list[Inventory.InventoryItem]:
        here = self.Assigned(self.slot)
        rest = [item for item in super().Visible() if item.itemID not in here]
        if any(self.byID[itemID].armor in Utils.THREE_PIECE for itemID in here):
            rest = [item for item in rest if item.armor in Utils.THREE_PIECE]
        return sorted((self.byID[itemID] for itemID in here), key=PieceOrder) + rest

    def Title(self) -> str:
        return Say(Text.SHOWCASE_EDIT_TITLE)

    def SelectionLine(self, chosen: list[Inventory.InventoryItem]) -> str:
        count = len(set(self.assign.values()))
        return Say(Text.SHOWCASE_CLEAR_ALL_CONFIRM, count=count, s=Utils.PluralS(count)) if self.confirming else ""

    async def Preview(self) -> tuple[discord.File, discord.ui.MediaGallery] | None:
        pieces = sorted((self.byID[itemID] for itemID in self.Assigned(self.slot)), key=PieceOrder)
        if not pieces:
            return None
        key = tuple((piece.itemID, piece.hexCode) for piece in pieces)
        if key != self.previewKey:
            self.previewKey, self.previewVersion = key, self.previewVersion + 1
            self.previewPNG = await asyncio.to_thread(InventoryCard.RenderPreview, pieces)
        name = f"preview{self.previewVersion}.png"
        return discord.File(io.BytesIO(self.previewPNG), filename=name), discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{name}", description=InventoryPanel.Alt(pieces)))

    def SlotOption(self, slot: Utils.SlotIndex) -> discord.SelectOption:
        pieces = [self.byID[itemID] for itemID in self.Assigned(slot)]
        label = Say(Text.SHOWCASE_SLOT_OPTION, slot=slot, armor=Say(Text.SHOWCASE_THREE_PIECE) if len({piece.armor for piece in pieces}) > 1 else Inventory.ArmorLabel(pieces[0].armor), count=len(pieces), s=Utils.PluralS(len(pieces))) if pieces else Say(Text.SHOWCASE_SLOT_OPTION_EMPTY, slot=slot)
        return discord.SelectOption(label=label[:100], value=str(slot), emoji="\u2B50" if slot in self.earn else None, default=slot == self.slot)

    def HeaderRows(self) -> list[discord.ui.ActionRow]:
        filled = self.slot in self.assign.values()
        earning = self.slot in self.earn
        first = (self.slot - 1) // slotsPerMenu * slotsPerMenu + 1
        options = [self.SlotOption(slot) for slot in range(first, min(first + slotsPerMenu, self.slotCount + 1))]
        return [
            discord.ui.ActionRow(Views.Dropdown(Say(Text.SHOWCASE_PLACEHOLDER_SLOT), options, self.OnSlot)),
            discord.ui.ActionRow(
                Views.Button(Say(Text.INVENTORY_BUTTON_PREV), functools.partial(self.OnStep, -1), disabled=self.slot <= 1),
                Views.Button(Say(Text.SHOWCASE_BUTTON_SLOT, slot=self.slot, max=self.slotCount), disabled=True),
                Views.Button(Say(Text.INVENTORY_BUTTON_NEXT), functools.partial(self.OnStep, 1), disabled=self.slot >= self.slotCount),
                *([
                    Views.Button(Say(Text.SHOWCASE_BUTTON_EARN_ON if earning else Text.SHOWCASE_BUTTON_EARN_OFF), self.OnEarn, discord.ButtonStyle.primary if earning else discord.ButtonStyle.secondary),
                    Views.Button(Say(Text.SHOWCASE_BUTTON_CLEAR), self.OnClearSlot, discord.ButtonStyle.danger),
                ] if filled else []),
            ),
        ]

    def ActionButtons(self, selectedCount: int) -> tuple[list[discord.ui.Button], discord.Color]:
        if self.confirming:
            return [
                Views.Button(Say(Text.SHOWCASE_BUTTON_CONFIRM), self.OnConfirmClearAll, discord.ButtonStyle.danger),
                Views.Button(Say(Text.SHOWCASE_BUTTON_CANCEL), self.OnCancel),
            ], discord.Color.red()
        return [
            Views.Button(Say(Text.SHOWCASE_BUTTON_CLEAR_ALL), self.OnClearAll, discord.ButtonStyle.danger, disabled=not self.assign),
            Views.Button(Say(Text.INVENTORY_BUTTON_SEARCH), self.OnSearch),
            Views.Button(Say(Text.INVENTORY_BUTTON_RESET), self.OnReset, disabled=not self.filters.active),
        ], Variables.defaultDiscordColor

    @Views.ButtonCallback
    async def OnSlot(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.GoTo(int(interaction.data["values"][0]))
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnStep(self, step: int, interaction: discord.Interaction):
        self.Touch(interaction)
        self.GoTo(self.slot + step)
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnEarn(self, interaction: discord.Interaction):
        self.Touch(interaction)
        full = False
        if self.slot in self.earn:
            self.earn.remove(self.slot)
        elif len(self.earn) < self.capacity:
            self.earn.append(self.slot)
        else:
            full = True
        await self.Show(interaction)
        if full:
            await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.SHOWCASE_TOO_MANY, max=self.capacity), ephemeral=True)

    @Views.ButtonCallback
    async def OnClearSlot(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.selected = set()
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnClearAll(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.confirming = bool(self.assign)
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnCancel(self, interaction: discord.Interaction):
        self.Touch(interaction)
        await self.Show(interaction)

    @Views.ButtonCallback
    async def OnConfirmClearAll(self, interaction: discord.Interaction):
        self.Touch(interaction)
        self.assign, self.earn, self.selected, self.known = {}, [], set(), set()
        self.filters.armor = None
        await self.Show(interaction)

@MainBot.AppCommandWithAliases(
    showcaseGroup,
    name="view",
    description=Say(Text.SHOWCASE_VIEW_DESCRIPTION),
    guildOnly=True,
    variableDescriptions={
        "user": Say(Text.SHOWCASE_USER),
    },
)
async def Command_ShowcaseView(interaction: discord.Interaction, user: discord.Member | None = None):
    await interaction.response.defer(thinking=True)
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)

    await InventoryPanel.SendShowcase(interaction, guildID, interaction.user.id if user is None else user.id)

@MainBot.AppCommandWithAliases(
    showcaseGroup,
    name="edit",
    description=Say(Text.SHOWCASE_EDIT_DESCRIPTION),
    guildOnly=True,
)
async def Command_ShowcaseEdit(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)

    profile = await Profiles.EnsureProfile(guildID, interaction.user.id)
    await ShowcasePanel(guildID, interaction.user.id, profile).Start(interaction)
