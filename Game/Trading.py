import MainBot

import discord
import asyncio
import json

from dataclasses import dataclass, field
from enum import Enum

from Database import PersistentUserData
from Utils.Translation import Say, Text
from Database import Atomic
from Game import Profiles
from Utils import Logger
from Utils import Utils

tradesByMessage: dict[Utils.MessageID, "TradeData"] = {}
busyUsers: dict[tuple[Utils.GuildID, Utils.MemberID], "TradeData"] = {}

class TradeState(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"

@dataclass(slots=True, eq=False)
class TradeData:
    guildID: Utils.GuildID
    sender: Utils.MemberID
    recipient: Utils.MemberID
    senderItems: list[Utils.ItemID]
    recipientItems: list[Utils.ItemID]
    offerCoins: int
    requestCoins: int
    message: discord.Message | None = field(default=None, init=False)
    state: TradeState = field(default=TradeState.PENDING, init=False)

    def HasItem(self, itemID: Utils.ItemID) -> bool:
        return itemID in self.senderItems or itemID in self.recipientItems

    def BusyKeys(self) -> tuple:
        return (self.guildID, self.sender), (self.guildID, self.recipient)

def IsMemberBusy(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
) -> bool:
    return (guildID, userID) in busyUsers

def IsItemPending(
    guildID: Utils.GuildID,
    itemID: Utils.ItemID,
) -> bool:
    return any(
        trade.guildID == guildID and trade.HasItem(itemID)
        for trade in tradesByMessage.values()
    )

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

async def CloseTrade(
    trade: TradeData,
    title: str,
    description: str,
) -> None:
    Free(trade)
    embed = MainBot.CreateDefaultEmbed(
        title=Say(Text.TRADE_TITLE, title=title, sender=trade.sender, recipient=trade.recipient)[:256],
        description=description,
        color=discord.Color.greyple(),
    )
    try:
        await trade.message.edit(embed=embed, view=None)
    except discord.HTTPException:
        pass

async def Reply(
    interaction: discord.Interaction,
    message: str,
) -> None:
    await Logger.SendInteractionMessage(interaction=interaction, message=message, ephemeral=True)

async def Claim(
    interaction: discord.Interaction,
    role: str,
    newState: TradeState,
) -> TradeData | None:
    trade = tradesByMessage.get(interaction.message.id)
    if trade is None or trade.state is not TradeState.PENDING:
        await Reply(interaction, Say(Text.TRADE_NOT_PENDING))
        return None
    if interaction.user.id != getattr(trade, role):
        await Reply(interaction, Say(Text.TRADE_NOT_YOURS))
        return None
    trade.state = newState
    return trade

async def Expire(trade: TradeData) -> None:
    await asyncio.sleep(Utils.GetSettingValueFromGuild(trade.guildID, Utils.Setting.TRADE_TIMEOUT_SECONDS))
    if trade.state is TradeState.PENDING:
        trade.state = TradeState.EXPIRED
        await CloseTrade(trade, Say(Text.TRADE_EXPIRED_TITLE), Say(Text.TRADE_EXPIRED_BODY))

def ArmTimeout(trade: TradeData) -> None:
    MainBot.FireAndForget(Expire(trade))

def AcceptBuild(trade: TradeData):
    guildID = trade.guildID
    sides = (
        (trade.sender, trade.recipient, trade.senderItems),
        (trade.recipient, trade.sender, trade.recipientItems),
    )
    payments = (
        (trade.sender, trade.offerCoins),
        (trade.recipient, trade.requestCoins),
    )

    def build():
        scopes = {uid: Profiles.Scope(guildID, uid) for uid in (trade.sender, trade.recipient)}
        profiles = {}
        for uid, scope in scopes.items():
            profile = Profiles.CachedProfile(scope)
            if profile is None:
                raise ValueError(Say(Text.TRADE_NO_PROFILE))
            profiles[uid] = profile

        for payer, cost in payments:
            if profiles[payer]["coins"] < cost:
                raise ValueError(Say(Text.TRADE_NO_COINS, payer=payer))

        userUpdates = {scope: {} for scope in scopes.values()}
        appUpdates = {}
        for giver, taker, itemIDs in sides:
            owned = PersistentUserData.persistentUserData.get(scopes[giver], {})
            for itemID in itemIDs:
                row = owned.get(f"item.{itemID}")
                if row is None:
                    raise ValueError(Say(Text.TRADE_NOT_OWNER, giver=giver, itemID=itemID))
                userUpdates[scopes[giver]][f"item.{itemID}"] = None
                userUpdates[scopes[taker]][f"item.{itemID}"] = json.loads(row)
                appUpdates[f"itemOwner.{guildID}.{itemID}"] = taker
            given = set(itemIDs)
            Profiles.Unshowcase(profiles[giver], given)

        delta = trade.requestCoins - trade.offerCoins
        profiles[trade.sender]["coins"] += delta
        profiles[trade.recipient]["coins"] -= delta

        for uid, profile in profiles.items():
            userUpdates[scopes[uid]]["profile"] = profile

        itemCount = len(trade.senderItems) + len(trade.recipientItems)
        return userUpdates, appUpdates, itemCount

    return build

async def HandleAccept(interaction: discord.Interaction) -> None:
    trade = await Claim(interaction, "recipient", TradeState.ACCEPTED)
    if trade is None:
        return
    try:
        await Profiles.EnsureProfile(trade.guildID, trade.sender)
        await Profiles.EnsureProfile(trade.guildID, trade.recipient)
        scopes = [Profiles.Scope(trade.guildID, uid) for uid in (trade.sender, trade.recipient)]
        itemCount = await Atomic.AtomicUpdate(
            trade.guildID,
            scopes,
            AcceptBuild(trade),
            useCommitLock=False,
        )
    except Exception as e:
        trade.state = TradeState.FAILED
        reason = Say(Text.TRADE_FAILED_REASON, error=str(e))
        await CloseTrade(trade, Say(Text.TRADE_FAILED_TITLE), reason)
        await Reply(interaction, reason)
        return
    await CloseTrade(trade, Say(Text.TRADE_DONE_TITLE), Say(Text.TRADE_DONE_BODY, sender=trade.sender, recipient=trade.recipient, count=itemCount, s=Utils.PluralS(itemCount)))
    await Reply(interaction, Say(Text.TRADE_DONE_REPLY))


async def Resolve(
    interaction: discord.Interaction,
    role: str,
    state: TradeState,
    title: Text,
    body: Text,
    reply: Text,
) -> None:
    trade = await Claim(interaction, role, state)
    if trade is None:
        return
    await CloseTrade(trade, Say(title), Say(body, userID=getattr(trade, role)))
    await Reply(interaction, Say(reply))

async def HandleDecline(interaction: discord.Interaction) -> None:
    await Resolve(interaction, "recipient", TradeState.DECLINED, Text.TRADE_DECLINED_TITLE, Text.TRADE_DECLINED_BODY, Text.TRADE_DECLINED_REPLY)

async def HandleCancel(interaction: discord.Interaction) -> None:
    await Resolve(interaction, "sender", TradeState.CANCELLED, Text.TRADE_CANCELLED_TITLE, Text.TRADE_CANCELLED_BODY, Text.TRADE_CANCELLED_REPLY)
