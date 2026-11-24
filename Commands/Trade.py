import MainBot

import discord
import asyncio

from Utils.Translation import Say, Text
from Game import InventoryPanel
from Game import InventoryCard
from Utils import Variables
from Game import Inventory
from Game import Profiles
from Game import Trading
from Utils import Logger
from Utils import Utils
from Utils import Views

async def AvatarBytes(member: discord.abc.User) -> bytes | None:
    try:
        return await member.display_avatar.replace(size=128, format="png").read()
    except (discord.HTTPException, OSError):
        return None

class CoinsModal(discord.ui.Modal):
    def __init__(self, panel: "TradePanel"):
        super().__init__(title=Say(Text.TRADE_COINS_MODAL_TITLE))
        self.panel = panel
        self.amount = discord.ui.TextInput(default=str(panel.coins) if panel.coins else "", required=False, max_length=24)
        self.add_item(discord.ui.Label(text=Say(Text.TRADE_COINS_LABEL), description=Say(Text.TRADE_COINS_HINT, balance=Utils.CompactNumber(panel.balance)), component=self.amount))

    @Views.ButtonCallback
    async def on_submit(self, interaction: discord.Interaction):
        self.panel.Touch(interaction)
        try:
            coins = int(InventoryPanel.ParseNumber(self.amount.value) or 0)
            if coins < 0:
                raise ValueError(coins)
        except ValueError:
            await self.panel.Show(interaction, Say(Text.TRADE_COINS_INVALID))
            return
        if coins > self.panel.balance:
            await self.panel.Show(interaction, Say(Text.TRADE_COINS_TOO_MANY, balance=Utils.CompactNumber(self.panel.balance)))
            return
        self.panel.coins = coins
        await self.panel.Show(interaction)

class TradePanel(InventoryPanel.InventoryPanel):
    allowEmpty = True
    emptyText = Text.TRADE_PANEL_NO_ITEMS
    maxSelected = Trading.maxTradeItems

    def __init__(self, trade: Trading.TradeData, userID: Utils.MemberID):
        super().__init__(trade.guildID, userID, Text.TRADE_PANEL_EXPIRED)
        self.trade = trade
        self.selected = set(trade.items[userID])
        self.coins = trade.coins[userID]
        self.balance = 0

    def Pending(self) -> set[Utils.ItemID]:
        return set()

    def Touch(self, interaction: discord.Interaction) -> None:
        super().Touch(interaction)
        Trading.Touch(self.trade)

    async def Load(self) -> None:
        await super().Load()
        self.balance = Profiles.CachedProfile(Profiles.Scope(self.guildID, self.ownerID))["coins"]
        if self.coins > self.balance:
            self.coins = self.balance
            self.status = Say(Text.TRADE_COINS_TOO_MANY, balance=Utils.CompactNumber(self.balance))
        itemIDs = sorted(self.selected, key=lambda itemID: Inventory.SortKey(Inventory.SortMode.RARITY_DESC, self.byID[itemID]))
        if Trading.SetOffer(self.trade, self.ownerID, itemIDs, self.coins):
            MainBot.FireAndForget(self.trade.view.Refresh())

    def Title(self) -> str:
        return Say(Text.TRADE_PANEL_TITLE, user=self.trade.Other(self.ownerID))

    def SelectionLine(self, chosen: list[Inventory.InventoryItem]) -> str:
        line = Say(
            Text.TRADE_PANEL_OFFER,
            count=len(chosen),
            s=Utils.PluralS(len(chosen)),
            value=Utils.CompactNumber(sum(item.value for item in chosen)),
            coins=Utils.CompactNumber(self.coins),
            balance=Utils.CompactNumber(self.balance),
        )
        return line + self.HiddenNote(chosen)

    def ActionButtons(self, selectedCount: int) -> tuple[list[discord.ui.Button], discord.Color]:
        return [
            Views.Button(Say(Text.TRADE_BUTTON_COINS), self.OnCoins),
            *self.CommonButtons(selectedCount),
        ], Variables.defaultDiscordColor

    async def Show(self, interaction: discord.Interaction, status: str = "") -> None:
        if self.trade.isOpen:
            await super().Show(interaction, status)
            return
        self.clear_items()
        self.add_item(discord.ui.TextDisplay(Say(Text.TRADE_PANEL_ENDED)))
        if not interaction.response.is_done():
            await interaction.response.defer()
        await interaction.edit_original_response(view=self, attachments=[])

    async def OnCoins(self, interaction: discord.Interaction):
        await Views.OpenModal(interaction, CoinsModal(self))

class TradeTable(discord.ui.LayoutView):
    def __init__(self, trade: Trading.TradeData):
        super().__init__(timeout=None)
        self.trade = trade
        self.renders = 0
        self.refreshLock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in self.trade.Members():
            return True
        await interaction.response.send_message(Say(Text.TRADE_NOT_YOURS), ephemeral=True)
        return False

    def Header(self) -> str:
        trade = self.trade
        text = Text.TRADE_HEADER_INVITE if trade.state is Trading.TradeState.INVITED else Text.TRADE_HEADER_OFFERING
        return Say(text, sender=trade.sender, recipient=trade.recipient)

    def Name(self, userID: Utils.MemberID) -> str:
        safe = "".join(char for char in self.trade.names.get(userID, "") if " " <= char <= "~").strip()
        return safe or Say(Text.TRADE_NAME_FALLBACK, number=1 + (userID != self.trade.sender))

    def Buttons(self) -> list[discord.ui.Button]:
        cancel = Views.Button(Say(Text.TRADE_BUTTON_CANCEL), self.OnCancel, discord.ButtonStyle.danger)
        match self.trade.state:
            case Trading.TradeState.INVITED:
                return [
                    Views.Button(Say(Text.TRADE_BUTTON_ACCEPT), self.OnAccept, discord.ButtonStyle.success),
                    cancel,
                ]
            case _:
                return [
                    Views.Button(Say(Text.TRADE_BUTTON_EDIT), self.OnEdit, discord.ButtonStyle.primary),
                    Views.Button(Say(Text.TRADE_BUTTON_LOCK), self.OnLock, discord.ButtonStyle.success),
                    cancel,
                ]

    async def Compose(self) -> list[discord.File]:
        trade = self.trade
        self.renders += 1
        files: list[discord.File] = []
        parts: list = [discord.ui.TextDisplay(self.Header())]
        if trade.state is not Trading.TradeState.INVITED:
            chosen = {userID: await Inventory.LoadSelected(trade.guildID, userID, trade.items[userID]) for userID in trade.Members()}
            worth = {userID: sum(item.value for item in chosen[userID]) for userID in trade.Members()}
            labels = [InventoryCard.SideLabel(self.Name(userID), userID in trade.ready, Trading.Describe(trade, userID, worth[userID]), Say(Text.TRADE_TOTAL, coins=Utils.CompactNumber(worth[userID] + trade.coins[userID])) if worth[userID] + trade.coins[userID] else "", trade.avatars.get(userID)) for userID in trade.Members()]
            files, gallery = await InventoryPanel.SidesGallery(chosen[trade.sender], chosen[trade.recipient], labels, f"trade{self.renders}")
            parts += [discord.ui.Separator(), gallery]
        parts += [discord.ui.Separator(), discord.ui.ActionRow(*self.Buttons())]

        self.clear_items()
        self.add_item(discord.ui.Container(*parts, accent_color=Variables.defaultDiscordColor))
        return files

    async def Finish(self) -> None:
        trade = self.trade
        Trading.Free(trade)
        chosen = [await Inventory.LoadSelected(trade.guildID, trade.Other(userID), trade.items[userID]) for userID in trade.Members()]
        labels = [InventoryCard.SideLabel(Say(Text.TRADE_LABEL_GAVE, name=self.Name(userID)), False, Trading.Describe(trade, userID), "", trade.avatars.get(userID)) for userID in trade.Members()]
        title = Say(Text.TRADE_TITLE, title=Say(Text.TRADE_DONE_TITLE), sender=trade.sender, recipient=trade.recipient)

        async def push():
            files, gallery = await InventoryPanel.SidesGallery(*chosen, labels, f"trade{self.renders + 1}")
            done = discord.ui.LayoutView(timeout=None)
            done.add_item(discord.ui.Container(discord.ui.TextDisplay(title), gallery, accent_color=discord.Color.greyple()))
            await trade.message.edit(view=done, attachments=files)

        try:
            await Views.Retry(push)
        except discord.HTTPException:
            pass

    async def Refresh(self) -> None:
        async with self.refreshLock:
            if not self.trade.isOpen:
                return

            async def push():
                files = await self.Compose()
                await self.trade.message.edit(view=self, attachments=files)

            try:
                await Views.Retry(push)
            except discord.HTTPException:
                pass

    @Views.ButtonCallback
    async def OnAccept(self, interaction: discord.Interaction):
        trade = await Trading.Guard(interaction, (Trading.TradeState.INVITED,), "recipient")
        if trade is None:
            return
        Trading.Accept(trade)
        await self.Refresh()

    @Views.ButtonCallback
    async def OnCancel(self, interaction: discord.Interaction):
        await Trading.HandleCancel(interaction)

    @Views.ButtonCallback
    async def OnEdit(self, interaction: discord.Interaction):
        trade = await Trading.Guard(interaction, (Trading.TradeState.OFFERING,))
        if trade is None:
            return
        await TradePanel(trade, interaction.user.id).Start(interaction)

    @Views.ButtonCallback
    async def OnLock(self, interaction: discord.Interaction):
        trade = await Trading.Guard(interaction, (Trading.TradeState.OFFERING,))
        if trade is None:
            return
        if not Trading.Lock(trade, interaction.user.id):
            await Logger.Reply(interaction, Say(Text.TRADE_EMPTY))
            return
        if trade.state is Trading.TradeState.EXECUTING:
            await Trading.Execute(trade, interaction)
        else:
            await self.Refresh()

@MainBot.AppCommandWithAliases(
    MainBot.GetClient().tree,
    name="trade",
    description=Say(Text.TRADE_DESCRIPTION),
    guildOnly=True,
    variableDescriptions={
        "user": Say(Text.GLOBAL_USER),
    },
)
async def Command_Trade(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)
    channel = await Utils.RequireChannel(interaction)

    sender = interaction.user.id
    recipient = user.id
    if recipient == sender:
        await Utils.AbortCommand(interaction, Say(Text.TRADE_SELF_ERROR))
    if user.bot:
        await Utils.AbortCommand(interaction, Say(Text.TRADE_BOT_ERROR))
    if Trading.IsMemberBusy(guildID, sender):
        await Utils.AbortCommand(interaction, Say(Text.TRADE_YOU_BUSY))
    if Trading.IsMemberBusy(guildID, recipient):
        await Utils.AbortCommand(interaction, Say(Text.TRADE_THEY_BUSY, user=recipient))

    trade = Trading.TradeData(guildID, sender, recipient)
    trade.names = {
        sender: interaction.user.display_name,
        recipient: user.display_name,
    }
    trade.avatars = {member.id: await AvatarBytes(member) for member in (interaction.user, user)}
    trade.view = TradeTable(trade)
    files = await trade.view.Compose()
    trade.message = await channel.send(view=trade.view, files=files)
    Trading.Register(trade)
    Trading.ArmTimeout(trade)
    await Logger.Reply(interaction, Say(Text.TRADE_STARTED))
