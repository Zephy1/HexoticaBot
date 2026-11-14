import MainBot

import discord
import asyncio
import random
import time

from dataclasses import dataclass
from enum import StrEnum

from Utils.Translation import Say, Text
from Database import PersistentData
from Game import TemporaryBuffs
from Database import Atomic
from Utils import Variables
from Game import Profiles
from Game import Upgrades
from Utils import Logger
from Utils import Utils
from Utils import Views
from Game import Items
from Game import Lists

sendRetries = 3
sendRetryDelaySeconds = 2

drops: dict[Utils.MessageID, "Drop"] = {}
sendSemaphore = asyncio.Semaphore(8)
shuttingDown = False
textBudget = 3800
noMentions = discord.AllowedMentions.none()

class DropState(StrEnum):
    OPEN = "open"
    CLAIMING = "claiming"
    CLAIMED = "claimed"
    EXPIRED = "expired"

class DropType(StrEnum):
    TIMED = "timed"
    ROLL = "roll"
    ADMIN = "admin"

@dataclass(slots=True)
class Drop:
    guildID: Utils.GuildID
    channelID: Utils.ChannelID
    bundle: Lists.DropBundle
    extras: list[Lists.DropBundle]
    dropType: DropType = DropType.TIMED
    expiresAt: float = 0.0
    state: DropState = DropState.OPEN
    message: discord.Message | None = None
    bonusCoins: Utils.Coins = 0

    @property
    def bundles(self) -> list[Lists.DropBundle]:
        return [self.bundle, *self.extras]

class ClaimRow(discord.ui.ActionRow):
    @discord.ui.button(label=Say(Text.CLAIM_BUTTON), style=discord.ButtonStyle.primary, custom_id="hexotica:claim")
    @Views.ButtonCallback
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await HandleClaim(interaction)

def ClaimView() -> discord.ui.LayoutView:
    return discord.ui.LayoutView(timeout=None).add_item(ClaimRow())

def SetImageURL(bundle: Lists.DropBundle) -> str | None:
    return None

def Layout(
    color: discord.Color,
    header: str,
    sections: list[tuple[str | None, str]],
    claimable: bool = False,
) -> discord.ui.LayoutView:
    container = discord.ui.Container(discord.ui.TextDisplay(header), accent_colour=color)
    for imageURL, text in sections:
        container.add_item(discord.ui.Separator())
        if imageURL:
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(imageURL)))
        container.add_item(discord.ui.TextDisplay(text))
    if claimable:
        container.add_item(ClaimRow())
    container.add_item(discord.ui.TextDisplay(Say(Text.FOOTER_LINE, BOT_FOOTER=Variables.footerText)))
    return discord.ui.LayoutView().add_item(container)

def IsSpecial(guildID: Utils.GuildID, bundle: Lists.DropBundle) -> bool:
    return not bundle.void and bundle.rarity >= Utils.GetSettingValueFromGuild(guildID, Utils.Setting.SPECIAL_ALERT_THRESHOLD)

def SellValue(
    guildID: Utils.GuildID,
    rarity: float,
    multiplier: float = 1.0,
) -> Utils.Coins:
    rate = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.SELL_COIN_RATE)
    return int(max(rarity, 0) * rate * multiplier + 0.5)

async def BuildDrop(
    guildID: Utils.GuildID,
    luck: float,
    channelID: Utils.ChannelID,
    dropType: DropType = DropType.TIMED,
    rarityRange=None,
) -> Drop | None:
    bundle = await Lists.PickBundle(guildID, luck, rarityRange)
    if bundle is None:
        return None

    Lists.ReserveBundle(guildID, bundle)
    extras = []
    if random.random() < Utils.GetSettingValueFromGuild(guildID, Utils.Setting.BONUS_BUNDLE_CHANCE):
        bonus = await Lists.PickBundle(guildID, Utils.GetSettingValueFromGuild(guildID, Utils.Setting.BONUS_LUCK) * luck)
        if bonus is not None:
            Lists.ReserveBundle(guildID, bonus)
            extras.append(bonus)
    if random.random() < Utils.GetSettingValueFromGuild(guildID, Utils.Setting.VOID_BONUS_CHANCE):
        void = Lists.PickVoided(guildID, random.choices((1, 2, 3, 4), (25, 35, 25, 15))[0])
        if void is not None:
            extras.append(void)
    return Drop(guildID, channelID, bundle, extras, dropType)

def ReleaseReservations(drop: Drop) -> None:
    for bundle in drop.bundles:
        Lists.ReleaseBundle(drop.guildID, bundle)

def PieceLine(piece: Lists.BundlePiece, detailed: bool = True) -> str:
    craft = Items.CraftText(piece.craft).replace("\n", "\n  ") if detailed else ""
    line = Say(Text.PIECE_LINE, name=piece.name, hex=piece.hex, rarity=Items.FormatRarity(piece.rarity))
    return line + (Say(Text.PIECE_CRAFT, craft=craft) if craft else "")

def BundleTitle(drop: Drop, bundle: Lists.DropBundle) -> str:
    if bundle is drop.bundle:
        return bundle.name
    return Say(Text.BUNDLE_BONUS_VOID, name=bundle.name.lower()) if bundle.void else Say(Text.BUNDLE_BONUS_SET, name=bundle.name)

def BundleLines(drop: Drop, bundle: Lists.DropBundle, detailed: bool = True) -> list[str]:
    lines = [Say(Text.BUNDLE_HEADER, title=BundleTitle(drop, bundle), rarity=Items.FormatRarity(bundle.rarity))]
    if bundle.info:
        lines.append(Items.SetText(bundle.info))
    lines.extend(PieceLine(piece, detailed) for piece in bundle.pieces)
    return lines

def BundleColor(bundles: list[Lists.DropBundle]) -> discord.Color:
    best = max((piece for bundle in bundles for piece in bundle.pieces), key=lambda piece: piece.rarity)
    return discord.Color(Utils.MinMaxHexInt(int(best.hex, 16)))

def DropLayout(drop: Drop) -> discord.ui.LayoutView:
    bundle = drop.bundle
    special = IsSpecial(drop.guildID, bundle)
    lines = "\n".join(PieceLine(piece) for piece in bundle.pieces)
    description = Say(Text.DROP_DESCRIPTION, rarity=Items.FormatRarity(bundle.rarity), setText=Items.SetText(bundle.info), lines=lines)
    if special:
        color = discord.Color.gold()
    else:
        color = BundleColor([bundle])
    return Layout(color, Say(Text.DROP_HEADER, star=Say(Text.SPECIAL_STAR) if special else "", name=bundle.name), [(SetImageURL(bundle), description[:textBudget])], claimable=True)

def ClaimedSections(drops: list[Drop], detailed: bool) -> list[tuple[str | None, str]]:
    sections = []
    for number, drop in enumerate(drops, start=1):
        for target in drop.bundles:
            lines = BundleLines(drop, target, detailed)
            if len(drops) > 1 and target is drop.bundle:
                lines[0] = Say(Text.DOUBLE_ROLL_LINE if number > 1 else Text.ROLL_LINE, line=lines[0])
            sections.append((SetImageURL(target), "\n".join(lines)))
        if drop.bonusCoins:
            image, text = sections[-1]
            sections[-1] = (image, Say(Text.CLAIMED_BONUS_COINS, text=text, coins=Utils.FormatNumber(drop.bonusCoins)))
    return sections

def ClaimedContent(drops: list[Drop], userID: Utils.MemberID) -> tuple[discord.Color, str, list[tuple[str | None, str]]]:
    special = any(IsSpecial(drop.guildID, drop.bundle) for drop in drops)
    star = Say(Text.SPECIAL_STAR) if special else ""
    name = drops[0].bundle.name if len(drops) == 1 else Say(Text.DOUBLE_ROLL)
    header = Say(Text.CLAIMED_HEADER, star=star, name=name, userID=userID)
    for detailed in (True, False):
        sections = ClaimedSections(drops, detailed)
        if len(header) + sum(len(text) for _, text in sections) <= textBudget:
            break
    return discord.Color.gold() if special else BundleColor([target for drop in drops for target in drop.bundles]), header, sections

def ClaimedLayout(drops: list[Drop], userID: Utils.MemberID) -> discord.ui.LayoutView:
    return Layout(*ClaimedContent(drops, userID))

def RollEmbed(drops: list[Drop], userID: Utils.MemberID, rolls: int) -> discord.Embed:
    color, header, sections = ClaimedContent(drops, userID)
    embed = MainBot.CreateDefaultEmbed(title="", description="\n\n".join([header, *(text for _, text in sections)]), createdAt=discord.utils.utcnow(), color=color)
    embed.set_footer(text=Say(Text.ROLL_FOOTER, BOT_FOOTER=Variables.footerText, rolls=rolls, s=Utils.PluralS(rolls)), icon_url=Variables.avatarLink)
    return embed

def ExpiredLayout(drop: Drop) -> discord.ui.LayoutView:
    return Layout(discord.Color.greyple(), Say(Text.EXPIRED_HEADER, name=drop.bundle.name), [(None, Say(Text.EXPIRED_BODY))])

def ClaimBuild(drops: list[Drop], userID: Utils.MemberID):
    guildID = drops[0].guildID
    targets = [target for drop in drops for target in drop.bundles]

    def build():
        scope = Profiles.Scope(guildID, userID)
        profile = Profiles.ClaimProfile(guildID, userID)
        sources = [(piece, target) for target in targets for piece in target.pieces]

        for drop in drops:
            drop.bonusCoins = SellValue(guildID, drop.bundle.rarity) if random.random() < Upgrades.BonusCoinsChance(profile, guildID) else 0
            profile["coins"] += drop.bonusCoins

        userItems, appUpdates, itemIDs = Items.AddItems(guildID, userID, sources)
        userUpdates = {scope: {"profile": profile, **userItems}}

        for target in targets:
            if target.void:
                for piece in target.pieces:
                    appUpdates[f"appData.void.{guildID}.{piece.voidID}"] = None
            else:
                appUpdates[f"appData.retired.{guildID}.{target.bundleID}"] = {
                    "claimedBy": userID,
                    "claimedAt": int(time.time()),
                }
        return userUpdates, appUpdates, itemIDs

    def onSuccess():
        for target in targets:
            if target.void:
                Lists.ConsumeVoidBundle(guildID, target)
            else:
                Lists.RetireImportedBundle(guildID, target)
    return build, onSuccess

def RollBuild(drops: list[Drop], userID: Utils.MemberID):
    build, onSuccess = ClaimBuild(drops, userID)
    guildID = drops[0].guildID
    scope = Profiles.Scope(guildID, userID)

    def rollBuild():
        userUpdates, appUpdates, itemIDs = build()
        held = int(PersistentData.ReadRowBlocking("pendingRoll", scope) or 0)
        if held >= 1:
            appUpdates[f"pendingRoll.{scope}"] = held - 1 or None
            profile = userUpdates[scope]["profile"]
            if random.random() < Upgrades.FreeRollChance(profile, guildID):
                profile["rolls"] += 1
        return userUpdates, appUpdates, itemIDs
    return rollBuild, onSuccess

def AnnounceClaim(drop: Drop, userID: Utils.MemberID) -> None:
    if any(IsSpecial(drop.guildID, bundle) for bundle in drop.bundles):
        MainBot.FireAndForget(SendSpecialAlert(drop, userID))

async def HandleClaim(interaction: discord.Interaction):
    drop = drops.get(interaction.message.id)
    user = interaction.user
    if drop is None:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.CLAIM_GONE), ephemeral=True)
        return
    if shuttingDown:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.CLAIM_SHUTDOWN), ephemeral=True)
        return
    if drop.state is not DropState.OPEN:
        await Logger.SendInteractionMessage(
            interaction=interaction,
            message=Say(Text.CLAIM_ALREADY_CLAIMED if drop.state is DropState.CLAIMED else Text.CLAIM_IN_PROGRESS),
            ephemeral=True,
        )
        return
    drop.state = DropState.CLAIMING
    try:
        await Profiles.EnsureProfile(drop.guildID, user.id)
        build, onSuccess = ClaimBuild([drop], user.id)
        await Atomic.AtomicUpdate(drop.guildID, [Profiles.Scope(drop.guildID, user.id)], build, onSuccess=onSuccess)
    except Exception as e:
        reason = str(e) or type(e).__name__
        await Logger.LogHeadlessError(f"Claim of drop {interaction.message.id} in guild {drop.guildID} failed: {reason}")
        if time.monotonic() >= drop.expiresAt:
            Expire(drop)
            await EditExpired(drop)
        else:
            drop.state = DropState.OPEN
            ArmExpiry(drop)
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.CLAIM_FAILED, reason=reason), ephemeral=True)
        return

    drop.state = DropState.CLAIMED
    drops.pop(interaction.message.id, None)
    await EditClaimed(drop, user.id)
    AnnounceClaim(drop, user.id)

async def RollDrop(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    channelID: Utils.ChannelID,
    interaction: discord.Interaction,
) -> str | None:
    held = await Profiles.HoldRoll(guildID, userID)
    if held is None:
        return Say(Text.ROLL_NO_ROLLS)
    profile, bonus = held
    luck = Profiles.RollerLuck(profile, guildID)
    claims: list[Drop] = []
    try:
        for _ in range(2 if random.random() < Upgrades.DoubleRollChance(profile, guildID) else 1):
            drop = await BuildDrop(guildID, luck, channelID=channelID, dropType=DropType.ROLL)
            if drop is None:
                break
            claims.append(drop)
        if claims:
            build, onSuccess = RollBuild(claims, userID)
            await Atomic.AtomicUpdate(guildID, [Profiles.Scope(guildID, userID)], build, onSuccess=onSuccess)
    except Exception as e:
        for drop in claims:
            ReleaseReservations(drop)
        await Profiles.ReleaseRoll(guildID, userID, bonus)
        reason = str(e) or type(e).__name__
        await Logger.LogHeadlessError(f"Roll in guild {guildID} failed: {reason}")
        return Say(Text.CLAIM_FAILED, reason=reason)
    if not claims:
        await Profiles.ReleaseRoll(guildID, userID, bonus)
        return Say(Text.ROLL_NOTHING_TO_DROP)
    for drop in claims:
        drop.state = DropState.CLAIMED
    rolls = Profiles.TotalRolls(Profiles.ClaimProfile(guildID, userID))
    message = await PostRoll(interaction, claims, userID, rolls)
    for claimed in claims:
        claimed.message = message
        AnnounceClaim(claimed, userID)
    return None if message is not None else Say(Text.ROLL_NOT_POSTED)

async def PostRoll(
    interaction: discord.Interaction,
    claims: list[Drop],
    userID: Utils.MemberID,
    rolls: int,
) -> discord.Message | None:
    lastError = None
    for attempt in range(sendRetries + 1):
        try:
            return await interaction.edit_original_response(embed=RollEmbed(claims, userID, rolls), allowed_mentions=noMentions)
        except discord.HTTPException as e:
            lastError = e
        if attempt < sendRetries:
            await asyncio.sleep(sendRetryDelaySeconds)
    await Logger.LogHeadlessError(f"Failed to post a roll result in guild {claims[0].guildID}: {lastError}")
    return None

async def PostDrop(channel: Utils.SendableChannel, drop: Drop) -> discord.Message:
    message = await channel.send(view=DropLayout(drop))
    drop.message = message
    drop.expiresAt = time.monotonic() + Utils.GetSettingValueFromGuild(drop.guildID, Utils.Setting.CLAIM_EXPIRY_SECONDS)
    drops[message.id] = drop
    ArmExpiry(drop)
    return message

async def SpawnDrop(
    guildID: Utils.GuildID,
    channel: Utils.SendableChannel,
    rarityRange=None,
) -> Drop | None:
    drop = await BuildDrop(
        guildID,
        Utils.GetSettingValueFromGuild(guildID, Utils.Setting.TIMED_DROP_LUCK),
        channelID=channel.id,
        dropType=DropType.ADMIN,
        rarityRange=rarityRange,
    )
    if drop is None:
        return None
    try:
        await PostDrop(channel, drop)
    except Exception:
        ReleaseReservations(drop)
        raise
    return drop

def Expire(drop: Drop) -> None:
    ReleaseReservations(drop)
    drop.state = DropState.EXPIRED
    drops.pop(drop.message.id, None)

async def EditExpired(drop: Drop) -> None:
    try:
        await drop.message.edit(view=ExpiredLayout(drop))
    except discord.HTTPException:
        pass

async def EditClaimed(drop: Drop, userID: Utils.MemberID) -> None:
    try:
        await drop.message.edit(view=ClaimedLayout([drop], userID), allowed_mentions=noMentions)
    except discord.HTTPException:
        pass

def ArmExpiry(drop: Drop) -> None:
    async def expire():
        delay = drop.expiresAt - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        if drop.state is not DropState.OPEN:
            return
        Expire(drop)
        await EditExpired(drop)
    MainBot.FireAndForget(expire())

async def SendSpecialAlert(drop: Drop, userID: Utils.MemberID) -> None:
    try:
        config = Utils.GuildConfig(drop.guildID)
        channelID = config.get("specialChannelID") or drop.channelID
        if not channelID:
            return
        channel = MainBot.GetClient().get_channel(channelID)
        if channel is None:
            return
        description = Say(Text.SPECIAL_ALERT, userID=userID, name=drop.bundle.name, rarity=Items.FormatRarity(drop.bundle.rarity))
        if drop.message:
            description += Say(Text.SPECIAL_ALERT_LINK, guildID=drop.guildID, channelID=drop.channelID, messageID=drop.message.id)
        for extra in drop.extras:
            if IsSpecial(drop.guildID, extra):
                description += Say(Text.SPECIAL_ALERT_EXTRA, name=extra.name, rarity=Items.FormatRarity(extra.rarity))
        await channel.send(embed=MainBot.CreateDefaultEmbed(title=Say(Text.SPECIAL_ALERT_TITLE), description=description[:4000], color=discord.Color.gold()))
    except discord.HTTPException:
        pass

def DropDelay(guildID: Utils.GuildID) -> float:
    low = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.DROP_INTERVAL_MIN_SECONDS)
    high = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.DROP_INTERVAL_MAX_SECONDS)
    return random.uniform(min(low, high), max(low, high)) / TemporaryBuffs.BeaconMultiplier(guildID, "frequency")

async def SpawnLoop():
    client = MainBot.GetClient()
    await client.wait_until_ready()
    nextDrops: dict[Utils.GuildID, float] = {}
    lastBeaconMult: dict[Utils.GuildID, float] = {}
    while not shuttingDown:
        try:
            await SpawnCycle(client, nextDrops, lastBeaconMult)
        except Exception as e:
            await Logger.LogHeadlessError(f"Error in SpawnLoop: {e}")
            await asyncio.sleep(60)

async def SpawnCycle(
    client: discord.Client,
    nextDrops: dict[Utils.GuildID, float],
    lastBeaconMult: dict[Utils.GuildID, float],
) -> None:
    now = time.time()
    wake = now + 15
    plans = []
    for guild in list(client.guilds):
        config = Utils.GuildConfig(guild.id)
        channelID = config.get("dropChannelID")
        if channelID is None:
            nextDrops.pop(guild.id, None)
            lastBeaconMult.pop(guild.id, None)
            continue
        multiplier = TemporaryBuffs.BeaconMultiplier(guild.id, "frequency")
        nextTick = nextDrops.get(guild.id)
        if nextTick is None:
            nextTick = now + DropDelay(guild.id)
        elif nextTick > now and guild.id in lastBeaconMult:
            last = lastBeaconMult[guild.id]
            if last != multiplier:
                nextTick = now + (nextTick - now) * last / multiplier
        nextDrops[guild.id] = nextTick
        lastBeaconMult[guild.id] = multiplier
        plans.append((guild, channelID, nextTick))
        wake = min(wake, nextTick)
    await asyncio.sleep(max(0.1, wake - time.time()))
    if shuttingDown:
        return
    now = time.time()
    due = [(guild, channelID) for guild, channelID, tick in plans if now >= tick]
    for guild, _ in due:
        nextDrops[guild.id] = now + DropDelay(guild.id)
    results = await asyncio.gather(
        *(SendTimedDrop(guild, channelID) for guild, channelID in due),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            await Logger.LogHeadlessError(f"Unexpected error sending timed drop: {result!r}")

async def SendTimedDrop(guild, channelID: Utils.ChannelID) -> None:
    if shuttingDown:
        return
    drop = await BuildDrop(guild.id, Utils.GetSettingValueFromGuild(guild.id, Utils.Setting.TIMED_DROP_LUCK) * TemporaryBuffs.BeaconMultiplier(guild.id, "luck"), channelID=channelID, dropType=DropType.TIMED)
    if drop is None:
        return
    channel = MainBot.GetClient().get_channel(channelID)
    if channel is None:
        ReleaseReservations(drop)
        return
    permissions = channel.permissions_for(guild.me)
    if not (permissions.send_messages and permissions.embed_links):
        ReleaseReservations(drop)
        return

    lastError = None
    async with sendSemaphore:
        for attempt in range(sendRetries + 1):
            try:
                await PostDrop(channel, drop)
                return
            except asyncio.TimeoutError:
                ReleaseReservations(drop)
                return
            except discord.HTTPException as e:
                lastError = e
            except Exception as e:
                lastError = e
                break
            if attempt < sendRetries:
                await asyncio.sleep(sendRetryDelaySeconds)
    ReleaseReservations(drop)
    await Logger.LogHeadlessError(f"Timed drop for guild {guild.id} skipped this cycle: {lastError}")

async def ShutdownDrops():
    global shuttingDown
    shuttingDown = True
    await Atomic.WaitCommitsIdle(5)
    openDrops = [drop for drop in drops.values() if drop.state is DropState.OPEN]
    for drop in openDrops:
        Expire(drop)
    if openDrops:
        try:
            async with asyncio.timeout(10):
                await asyncio.gather(*(EditExpired(drop) for drop in openDrops), return_exceptions=True)
        except TimeoutError:
            pass
