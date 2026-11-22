import MainBot

import discord
import asyncio

from Utils.Translation import Say, Text
from Game import TemporaryBuffs
from Game import InventoryPanel
from Commands import Collection
from Game import InventoryCard
from Utils import Variables
from Commands import Stats
from Game import Inventory
from Game import Upgrades
from Game import Profiles
from Utils import Utils
from Utils import Views
from Game import Drops

topRarestSetsCount = 5

class ProfileView(discord.ui.LayoutView):
    def __init__(self, interaction: discord.Interaction, guildID: Utils.GuildID, targetID: Utils.MemberID, parts: list):
        super().__init__(timeout=Views.panelTimeoutSeconds)
        self.interaction = interaction
        self.guildID = guildID
        self.targetID = targetID
        self.buttons = discord.ui.ActionRow(
            Views.Button(Say(Text.PROFILE_BUTTON_COLLECTION), self.OnCollection, discord.ButtonStyle.success),
            Views.Button(Say(Text.PROFILE_BUTTON_SHOWCASE), self.OnShowcase),
            Views.Button(Say(Text.PROFILE_BUTTON_STATS), self.OnStats, discord.ButtonStyle.danger),
        )
        self.add_item(discord.ui.Container(*parts, accent_color=Variables.defaultDiscordColor))
        self.add_item(self.buttons)

    async def on_timeout(self) -> None:
        self.remove_item(self.buttons)
        try:
            await self.interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass

    @Views.ButtonCallback(thinking=True)
    async def OnCollection(self, interaction: discord.Interaction):
        await Collection.CollectionPanel(self.guildID, interaction.user.id, self.targetID).Start(interaction)

    @Views.ButtonCallback(thinking=True)
    async def OnShowcase(self, interaction: discord.Interaction):
        await InventoryPanel.SendShowcase(interaction, self.guildID, self.targetID, ephemeral=True)

    @Views.ButtonCallback(thinking=True)
    async def OnStats(self, interaction: discord.Interaction):
        await Stats.SendStats(interaction, self.guildID, self.targetID)

def LuckLines(profile: dict, guildID: Utils.GuildID) -> list[str]:
    base = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.ROLL_BASE_LUCK)
    upgrades = Upgrades.Compound(profile, guildID, "luck")
    potion = TemporaryBuffs.LuckPotionMultiplier(profile, guildID)
    sources = []
    if base != 1:
        sources.append(Say(Text.PROFILE_LUCK_BASE, value=base))
    if upgrades != 1:
        sources.append(Say(Text.PROFILE_LUCK_UPGRADES, value=upgrades))
    if potion != 1:
        sources.append(Say(Text.PROFILE_LUCK_POTION, value=potion, until=int(TemporaryBuffs.WallTime(profile["luckClockUntil"]))))
    lines = [Say(Text.PROFILE_LUCK, luck=Profiles.RollerLuck(profile, guildID))]
    if sources:
        lines.append(Say(Text.PROFILE_LUCK_SOURCES, sources=Say(Text.PROFILE_SEPARATOR).join(sources)))
    return lines

def UpgradeList(profile: dict, guildID: Utils.GuildID) -> list[str]:
    return [
        Say(Text.PROFILE_UPGRADE if maxLevel is not None else Text.PROFILE_UPGRADE_UNCAPPED, label=label, level=level if maxLevel is None else min(level, maxLevel), max=maxLevel)
        for label, level, maxLevel, _, _ in Upgrades.UpgradeSummary(profile, guildID)
        if level > 0
    ]

@MainBot.AppCommandWithAliases(
    MainBot.GetClient().tree,
    name="profile",
    description=Say(Text.PROFILE_DESCRIPTION),
    guildOnly=True,
    variableDescriptions={"user": Say(Text.PROFILE_USER)},
)
async def Command_Profile(interaction: discord.Interaction, user: discord.Member | None = None):
    await interaction.response.defer(thinking=True)
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)

    target = interaction.user if user is None else user
    if target.id == interaction.user.id:
        profile = await Profiles.EnsureProfile(guildID, target.id)
    else:
        profile = await Profiles.PeekProfile(guildID, target.id)
        if profile is None:
            await Utils.AbortCommand(interaction, Say(Text.NO_PROFILE_USER))

    scope = Profiles.Scope(guildID, target.id)
    items = await Inventory.LoadItems(guildID, target.id, profile, set())
    rarest = Inventory.Arrange(items, Inventory.InventoryFilter(), Inventory.SortMode.RARITY_DESC)[:topRarestSetsCount]
    stats = profile.get("stats", {})

    bonusRolls = profile.get("bonusRolls", 0)
    lines = [
        Say(Text.PROFILE_TITLE, user=target.display_name),
        Say(Text.PROFILE_COINS, coins=Utils.CompactNumber(profile["coins"])),
        Say(Text.PROFILE_COINS_EARNED, coins=Stats.CoinCount(stats, "coins.gained")),
        Say(Text.PROFILE_COINS_SPENT, coins=Stats.CoinCount(stats, "coins.spent")),
        "",
        Say(Text.PROFILE_ROLLS, rolls=profile["rolls"], ceiling=Profiles.RollCeiling(profile, guildID), bonus=Say(Text.PROFILE_BONUS_ROLLS, bonus=bonusRolls) if bonusRolls > 0 else ""),
        Say(Text.PROFILE_REFILL, next=(Utils.CurrentHour() + 1) * 3600),
        *LuckLines(profile, guildID),
        "",
        Say(Text.PROFILE_VALUE, coins=Utils.CompactNumber(sum(item.value for item in items))),
        Say(Text.PROFILE_ITEMS, count=Utils.FormatNumber(len(items))),
        Say(Text.PROFILE_RAREST) + ("" if rarest else f" {Say(Text.PROFILE_NONE)}"),
    ]
    parts = [discord.ui.Section(discord.ui.TextDisplay("\n".join(lines)), accessory=discord.ui.Thumbnail(target.display_avatar.url))]
    files: list[discord.File] = []
    if rarest:
        png = await asyncio.to_thread(InventoryCard.Render, rarest, set(), columns=len(rarest))
        parts.append(Drops.ImageGallery(png, "rarest.png", InventoryPanel.Alt(rarest), files))
    parts.append(discord.ui.Separator())
    parts.append(discord.ui.TextDisplay("\n".join([
        Say(Text.PROFILE_SHOWCASE, used=len(profile["showcase"]), slots=Utils.GetSettingValueFromGuild(guildID, Utils.Setting.STARTING_SHOWCASE_SLOTS)),
        Say(Text.PROFILE_SHOWCASE_VALUE, coins=Utils.CompactNumber(sum(item.value for item in items if item.showcased))),
        Say(Text.PROFILE_SHOWCASE_INCOME, coins=Utils.CompactNumber(Profiles.ShowcaseIncome(profile, guildID, scope)), earning=len(Profiles.ActiveSlots(profile, guildID)), capacity=Profiles.EarningCapacity(profile, guildID)),
        "",
        Say(Text.PROFILE_UPGRADES, upgrades=", ".join(UpgradeList(profile, guildID)) or Say(Text.PROFILE_NONE)),
    ])))
    parts.append(discord.ui.TextDisplay(Drops.Footer()))
    await interaction.followup.send(view=ProfileView(interaction, guildID, target.id, parts), files=files, allowed_mentions=discord.AllowedMentions.none())
