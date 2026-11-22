import MainBot

import functools
import discord

from Utils.Translation import Say, Text
from Game import Inventory
from Game import Profiles
from Utils import Utils
from Utils import Views
from Game import Items

topArmors = 3
statsPeriods = {
    "day": Text.STATS_PERIOD_DAY,
    "week": Text.STATS_PERIOD_WEEK,
    "month": Text.STATS_PERIOD_MONTH,
    "all": Text.STATS_PERIOD_ALL,
}
statsTabs = {
    "overview": Text.STATS_TAB_OVERVIEW,
    "rolling": Text.STATS_TAB_ROLLING,
    "selling": Text.STATS_TAB_SELLING,
    "coins": Text.STATS_TAB_COINS,
}

class StatsView(discord.ui.LayoutView):
    def __init__(self, guildID: Utils.GuildID, targetID: Utils.MemberID, avatarURL: str | None = None):
        super().__init__(timeout=Views.panelTimeoutSeconds)
        self.guildID = guildID
        self.targetID = targetID
        self.avatarURL = avatarURL
        self.tab = "overview"
        self.period = "all"

    def NavRow(self, options: dict, current: str, callback, selected: discord.ButtonStyle) -> discord.ui.ActionRow:
        return discord.ui.ActionRow(*(
            Views.Button(Say(label), functools.partial(callback, key), selected if key == current else discord.ButtonStyle.secondary, disabled=key == current)
            for key, label in options.items()
        ))

    async def Show(self) -> None:
        profile = await Profiles.PeekProfile(self.guildID, self.targetID)
        stats = Profiles.PeriodStats(profile, self.period)
        itemCount = len(await Inventory.LoadItems(self.guildID, self.targetID, profile, set())) if self.tab == "overview" else 0
        title = discord.ui.TextDisplay(Say(Text.STATS_TITLE, user=self.targetID, tab=Say(statsTabs[self.tab]), period=Say(statsPeriods[self.period]), since=profile["since"]))
        parts = [discord.ui.Section(title, accessory=discord.ui.Thumbnail(self.avatarURL)) if self.avatarURL else title, discord.ui.Separator()]
        for block in tabBlocks[self.tab](profile, stats, itemCount) if stats else [Say(Text.STATS_EMPTY)]:
            parts += [discord.ui.TextDisplay(block), discord.ui.Separator()]
        parts.append(self.NavRow(statsTabs, self.tab, self.OnTab, discord.ButtonStyle.primary))
        parts.append(self.NavRow(statsPeriods, self.period, self.OnPeriod, discord.ButtonStyle.success))
        self.clear_items()
        self.add_item(discord.ui.Container(*parts, accent_color=discord.Color.red()))

    @Views.ButtonCallback
    async def OnTab(self, tab: str, interaction: discord.Interaction):
        self.tab = tab
        await self.Show()
        await interaction.edit_original_response(view=self)

    @Views.ButtonCallback
    async def OnPeriod(self, period: str, interaction: discord.Interaction):
        self.period = period
        await self.Show()
        await interaction.edit_original_response(view=self)

def Count(stats: dict, key: str) -> str:
    return Utils.FormatNumber(stats.get(key, 0))

def CoinCount(stats: dict, key: str) -> str:
    return Utils.CompactNumber(stats.get(key, 0))

def Fastest(stats: dict) -> str:
    fastest = stats.get("claims.fastest")
    return Say(Text.PROFILE_NONE) if fastest is None else Say(Text.STATS_SECONDS, seconds=fastest)

def PieceBreakdown(stats: dict, prefix: str, header: Text) -> str:
    slots = "\n".join(Say(Text.STATS_ITEM, name=Inventory.SlotLabel(slot.value), count=Count(stats, f"{prefix}.slot.{slot.value}")) for slot in Utils.ArmorSlot)
    armors = sorted(
        ((key.removeprefix(f"{prefix}.armor."), count) for key, count in stats.items() if key.startswith(f"{prefix}.armor.")),
        key=lambda pair: pair[1],
        reverse=True,
    )[:topArmors]
    lines = [Say(header), Say(Text.STATS_SLOTS, slots=slots)]
    if armors:
        lines.append(Say(Text.STATS_TOP, armors="\n".join(Say(Text.STATS_ITEM, name=Inventory.ArmorLabel(armor), count=Utils.FormatNumber(count)) for armor, count in armors)))
    return "\n".join(lines)

def SoldBlock(stats: dict) -> str:
    pieces = stats.get("sold.pieces", 0)
    average = Utils.CompactNumber(round(stats.get("coins.from.sales", 0) / pieces)) if pieces else Say(Text.PROFILE_NONE)
    return Say(Text.STATS_SOLD, pieces=Count(stats, "sold.pieces"), coins=CoinCount(stats, "coins.from.sales"), average=average)

def BalanceBlock(profile: dict, stats: dict) -> str:
    return Say(Text.STATS_COINS, gained=CoinCount(stats, "coins.gained"), spent=CoinCount(stats, "coins.spent"), peak=Utils.CompactNumber(max(stats.get("coins.peak", 0), profile["coins"])), balance=Utils.CompactNumber(profile["coins"]))

def OverviewBlocks(profile: dict, stats: dict, itemCount: int) -> list[str]:
    return [
        Say(Text.STATS_OVERVIEW_ROLLING, rolls=Count(stats, "rolls.total"), claims=Count(stats, "claims.total"), best=Items.FormatRarity(stats.get("rolled.bestRarity", 0)), claim=Items.FormatRarity(stats.get("claimed.bestRarity", 0)), fastest=Fastest(stats)),
        SoldBlock(stats),
        BalanceBlock(profile, stats),
        Say(Text.STATS_PROGRESS, items=Utils.FormatNumber(itemCount), levels=Utils.FormatNumber(sum(profile["upgrades"].values())), trades=Count(stats, "trades.completed")),
    ]

def RollingBlocks(profile: dict, stats: dict, itemCount: int) -> list[str]:
    return [
        Say(Text.STATS_ROLLS, rolls=Count(stats, "rolls.total"), claims=Count(stats, "claims.total"), double=Count(stats, "rolls.double"), free=Count(stats, "rolls.free")),
        Say(Text.STATS_ROLLED, bundles=Count(stats, "rolled.bundles"), special=Count(stats, "rolled.special"), bonus=Count(stats, "rolled.bonus"), void=Count(stats, "rolled.void")),
        Say(Text.STATS_BEST, roll=Items.FormatRarity(stats.get("rolled.bestRarity", 0)), claim=Items.FormatRarity(stats.get("claimed.bestRarity", 0)), fastest=Fastest(stats)),
        PieceBreakdown(stats, "rolled", Text.STATS_ROLLED_PIECES),
    ]

def SellingBlocks(profile: dict, stats: dict, itemCount: int) -> list[str]:
    return [SoldBlock(stats), PieceBreakdown(stats, "sold", Text.STATS_SOLD_PIECES)]

def CoinsBlocks(profile: dict, stats: dict, itemCount: int) -> list[str]:
    return [
        BalanceBlock(profile, stats),
        Say(Text.STATS_COIN_SOURCES, sales=CoinCount(stats, "coins.from.sales"), bonus=CoinCount(stats, "coins.from.bonus"), procs=Count(stats, "bonus.procs"), income=CoinCount(stats, "coins.from.income")),
    ]

tabBlocks = {
    "overview": OverviewBlocks,
    "rolling": RollingBlocks,
    "selling": SellingBlocks,
    "coins": CoinsBlocks,
}

async def SendStats(interaction: discord.Interaction, guildID: Utils.GuildID, targetID: Utils.MemberID) -> None:
    member = interaction.guild.get_member(targetID) if interaction.guild else None
    view = StatsView(guildID, targetID, member.display_avatar.url if member else None)
    await view.Show()
    await interaction.followup.send(view=view, ephemeral=True)

@MainBot.AppCommandWithAliases(
    MainBot.GetClient().tree,
    name="stats",
    description=Say(Text.STATS_DESCRIPTION),
    guildOnly=True,
    variableDescriptions={
        "user": Say(Text.STATS_USER),
    },
)
async def Command_Stats(interaction: discord.Interaction, user: discord.Member | None = None):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)

    targetID = interaction.user.id if user is None else user.id
    if targetID == interaction.user.id:
        await Profiles.EnsureProfile(guildID, targetID)
    elif await Profiles.PeekProfile(guildID, targetID) is None:
        await Utils.AbortCommand(interaction, Say(Text.NO_PROFILE_USER))

    await SendStats(interaction, guildID, targetID)
