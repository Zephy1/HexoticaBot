import MainBot

import discord
import asyncio
import json
import time

from dataclasses import dataclass, field
from enum import Enum

from Database import PersistentUserData
from Utils.Translation import Say, Text
from Database import Atomic
from Game import Profiles
from Utils import Logger
from Utils import Utils

maxTradeItems = 24

tradesByMessage: dict[Utils.MessageID, "TradeData"] = {}
busyUsers: dict[tuple[Utils.GuildID, Utils.MemberID], "TradeData"] = {}

class TradeState(Enum):
    INVITED = "invited"
    OFFERING = "offering"
    EXECUTING = "executing"
    DONE = "done"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"

openStates = (TradeState.INVITED, TradeState.OFFERING)

@dataclass(slots=True, eq=False)
class TradeData:
    guildID: Utils.GuildID
    sender: Utils.MemberID
    recipient: Utils.MemberID
    items: dict[Utils.MemberID, list[Utils.ItemID]] = field(init=False)
    coins: dict[Utils.MemberID, int] = field(init=False)
    ready: set[Utils.MemberID] = field(default_factory=set, init=False)
    names: dict[Utils.MemberID, str] = field(default_factory=dict, init=False)
    avatars: dict[Utils.MemberID, bytes | None] = field(default_factory=dict, init=False)
    message: discord.Message | None = field(default=None, init=False)
    view: discord.ui.LayoutView | None = field(default=None, init=False)
    state: TradeState = field(default=TradeState.INVITED, init=False)
    lastActivity: float = field(default_factory=time.monotonic, init=False)

    def __post_init__(self) -> None:
        self.items = {self.sender: [], self.recipient: []}
        self.coins = {self.sender: 0, self.recipient: 0}

    def Members(self) -> tuple[Utils.MemberID, Utils.MemberID]:
        return self.sender, self.recipient

    def Other(self, userID: Utils.MemberID) -> Utils.MemberID:
        return self.recipient if userID == self.sender else self.sender

    def BusyKeys(self) -> tuple:
        return (self.guildID, self.sender), (self.guildID, self.recipient)

    @property
    def isOpen(self) -> bool:
        return self.state in openStates

def IsMemberBusy(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
) -> bool:
    return (guildID, userID) in busyUsers

def PendingItems(guildID: Utils.GuildID) -> set[Utils.ItemID]:
    return {
        itemID
        for trade in tradesByMessage.values()
        if trade.guildID == guildID
        for itemIDs in trade.items.values()
        for itemID in itemIDs
    }

def IsItemPending(
    guildID: Utils.GuildID,
    itemID: Utils.ItemID,
) -> bool:
    return itemID in PendingItems(guildID)

def Register(trade: TradeData) -> None:
    tradesByMessage[trade.message.id] = trade
    for key in trade.BusyKeys():
        busyUsers[key] = trade

def Free(trade: TradeData) -> None:
    if trade.message is not None:
        tradesByMessage.pop(trade.message.id, None)
    for key in trade.BusyKeys():
        if busyUsers.get(key) is trade:
            del busyUsers[key]

def Touch(trade: TradeData) -> None:
    trade.lastActivity = time.monotonic()

def Timeout(trade: TradeData) -> int:
    return Utils.GetSettingValueFromGuild(trade.guildID, Utils.Setting.TRADE_TIMEOUT_SECONDS)

def Describe(
    trade: TradeData,
    userID: Utils.MemberID,
    worth: int | None = None,
) -> list[tuple[str, bool]]:
    parts: list[tuple[str, bool]] = []
    count = len(trade.items[userID])
    if count:
        parts.append((Say(Text.TRADE_PART_ITEMS, count=count, s=Utils.PluralS(count)), False))
        if worth is not None:
            parts.append((Say(Text.TRADE_PART_WORTH, value=Utils.CompactNumber(worth)), True))
    if trade.coins[userID]:
        if parts:
            parts.append((Say(Text.TRADE_PART_JOIN), False))
        parts.append((Say(Text.TRADE_PART_COINS, coins=Utils.CompactNumber(trade.coins[userID])), True))
    return parts

async def CloseTrade(
    trade: TradeData,
    title: str,
    description: str,
) -> None:
    Free(trade)
    closed = discord.ui.LayoutView(timeout=None)
    text = Say(Text.TRADE_TITLE, title=title, sender=trade.sender, recipient=trade.recipient)
    closed.add_item(discord.ui.Container(discord.ui.TextDisplay(f"{text}\n{description}"), accent_color=discord.Color.greyple()))
    try:
        await trade.message.edit(view=closed, attachments=[])
    except discord.HTTPException:
        pass

async def Guard(
    interaction: discord.Interaction,
    states: tuple[TradeState, ...],
    role: str | None = None,
) -> TradeData | None:
    trade = tradesByMessage.get(interaction.message.id)
    if trade is None or trade.state not in states:
        await Logger.Reply(interaction, Say(Text.TRADE_NOT_PENDING))
        return None
    allowed = trade.Members() if role is None else (getattr(trade, role),)
    if interaction.user.id not in allowed:
        await Logger.Reply(interaction, Say(Text.TRADE_OWN_REQUEST if interaction.user.id in trade.Members() else Text.TRADE_NOT_YOURS))
        return None
    Touch(trade)
    return trade

async def Expire(trade: TradeData) -> None:
    while trade.isOpen:
        remaining = trade.lastActivity + Timeout(trade) - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)
            continue
        trade.state = TradeState.EXPIRED
        await CloseTrade(trade, Say(Text.TRADE_EXPIRED_TITLE), Say(Text.TRADE_EXPIRED_BODY))

def ArmTimeout(trade: TradeData) -> None:
    MainBot.FireAndForget(Expire(trade))

def Accept(trade: TradeData) -> None:
    trade.state = TradeState.OFFERING

def SetOffer(
    trade: TradeData,
    userID: Utils.MemberID,
    itemIDs: list[Utils.ItemID],
    coins: int,
) -> bool:
    if trade.state is not TradeState.OFFERING:
        return False
    if set(trade.items[userID]) == set(itemIDs) and trade.coins[userID] == coins:
        return False
    trade.items[userID] = list(itemIDs)
    trade.coins[userID] = coins
    trade.ready.clear()
    return True

def Lock(
    trade: TradeData,
    userID: Utils.MemberID,
) -> bool:
    if not any(trade.items.values()) and not any(trade.coins.values()):
        return False
    trade.ready.add(userID)
    if len(trade.ready) == 2:
        trade.state = TradeState.EXECUTING
    return True

def ExecuteBuild(trade: TradeData):
    guildID = trade.guildID
    members = trade.Members()

    def build():
        scopes = {uid: Profiles.Scope(guildID, uid) for uid in members}
        profiles = {uid: Profiles.RequiredProfile(guildID, uid, Text.TRADE_NO_PROFILE) for uid in members}

        for uid in members:
            if profiles[uid]["coins"] < trade.coins[uid]:
                raise ValueError(Say(Text.TRADE_NO_COINS, payer=uid))

        userUpdates = {scope: {} for scope in scopes.values()}
        appUpdates = {}
        for giver in members:
            taker = trade.Other(giver)
            owned = PersistentUserData.persistentUserData.get(scopes[giver], {})
            for itemID in trade.items[giver]:
                row = owned.get(f"item.{itemID}")
                if row is None:
                    raise ValueError(Say(Text.TRADE_NOT_OWNER, giver=giver, itemID=itemID))
                userUpdates[scopes[giver]][f"item.{itemID}"] = None
                userUpdates[scopes[taker]][f"item.{itemID}"] = json.loads(row)

        for uid in members:
            profile = profiles[uid]
            Profiles.Unshowcase(profile, trade.items[uid])
            profile["coins"] += trade.coins[trade.Other(uid)] - trade.coins[uid]
            Profiles.AddStat(profile, "trades.completed")
            Profiles.MaxStat(profile, "coins.peak", profile["coins"])
            userUpdates[scopes[uid]]["profile"] = profile

        return userUpdates, appUpdates, None

    return build

async def Execute(
    trade: TradeData,
    interaction: discord.Interaction,
) -> None:
    try:
        for uid in trade.Members():
            await Profiles.EnsureProfile(trade.guildID, uid)
        await Atomic.AtomicUpdate(
            trade.guildID,
            [Profiles.Scope(trade.guildID, uid) for uid in trade.Members()],
            ExecuteBuild(trade),
            useCommitLock=False,
        )
    except Exception as e:
        trade.state = TradeState.FAILED
        reason = Say(Text.TRADE_FAILED_REASON, error=str(e))
        await CloseTrade(trade, Say(Text.TRADE_FAILED_TITLE), reason)
        await Logger.Reply(interaction, reason)
        return
    trade.state = TradeState.DONE
    await Logger.Reply(interaction, Say(Text.TRADE_DONE_REPLY))
    await trade.view.Finish()

async def ShutdownTrades() -> None:
    await Atomic.WaitCommitsIdle(5)
    openTrades = [trade for trade in tradesByMessage.values() if trade.isOpen]
    for trade in openTrades:
        trade.state = TradeState.CANCELLED
    try:
        async with asyncio.timeout(10):
            await asyncio.gather(*(CloseTrade(trade, Say(Text.TRADE_CANCELLED_TITLE), Say(Text.TRADE_SHUTDOWN_BODY)) for trade in openTrades), return_exceptions=True)
    except TimeoutError:
        pass

async def HandleCancel(interaction: discord.Interaction) -> None:
    trade = await Guard(interaction, openStates)
    if trade is None:
        return
    trade.state = TradeState.CANCELLED
    await CloseTrade(trade, Say(Text.TRADE_CANCELLED_TITLE), Say(Text.TRADE_CANCELLED_BODY, userID=interaction.user.id))
    await Logger.Reply(interaction, Say(Text.TRADE_CANCELLED_REPLY))
