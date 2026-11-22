import MainBot

import discord
import asyncio
import random
import time
import io

from dataclasses import dataclass, field, replace
from string import capwords
from enum import StrEnum

from Utils.Translation import Say, Text
from Database import PersistentData
from Game import TemporaryBuffs
from Database import Atomic
from Utils import Variables
from Game import Profiles
from Game import Upgrades
from Game import RollCard
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
    postedAt: float = 0.0
    state: DropState = DropState.OPEN
    message: discord.Message | None = None
    bonusCoins: Utils.Coins = 0
    bonusLoot: list[tuple[str, int, int, str]] = field(default_factory=list)

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

def IsSpecial(guildID: Utils.GuildID, bundle: Lists.DropBundle) -> bool:
    return not bundle.void and bundle.rarity >= Utils.GetSettingValueFromGuild(guildID, Utils.Setting.SPECIAL_ALERT_THRESHOLD)

def SellValue(
    guildID: Utils.GuildID,
    rarity: float,
    multiplier: float = 1.0,
    setting: Utils.Setting = Utils.Setting.SELL_COIN_RATE,
) -> Utils.Coins:
    rate = Utils.GetSettingValueFromGuild(guildID, setting)
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

def BundleTitle(drop: Drop, bundle: Lists.DropBundle) -> str:
    if bundle is drop.bundle:
        return bundle.name
    return Say(Text.BUNDLE_BONUS_VOID, name=bundle.name.lower()) if bundle.void else Say(Text.BUNDLE_BONUS_SET, name=bundle.name)

def Byline(drop: Drop, userID: Utils.MemberID) -> str:
    return Say(Text.ROLLED_BY if drop.dropType is DropType.ROLL else Text.CLAIMED_BY, userID=userID)

def BundleColor(bundles: list[Lists.DropBundle]) -> discord.Color:
    best = max((piece for bundle in bundles for piece in bundle.pieces), key=lambda piece: piece.rarity)
    return discord.Color(Utils.MinMaxHexInt(int(best.hex, 16)))

def RollBundleHead(drops: list[Drop], drop: Drop, bundle: Lists.DropBundle, expired: bool) -> str:
    title = capwords(BundleTitle(drop, bundle)).removesuffix(" Set")
    if expired:
        title = Say(Text.TITLE_EXPIRED, title=title)
    if len(drops) > 1 and bundle is drop.bundle:
        title = Say(Text.DOUBLE_ROLL_LINE if drop is not drops[0] else Text.ROLL_LINE, line=title)
    return Say(
        Text.ROLL_HEADER,
        star=Say(Text.SPECIAL_STAR) + " " if IsSpecial(drop.guildID, bundle) else "",
        title=title,
        rarity=Items.FormatRarity(bundle.rarity),
    )

def LootHeader(drop: Drop) -> str:
    return Say(Text.BONUS_LOOT_HEADER, coins=Utils.CompactNumber(drop.bonusCoins))

def Footer(rolls: int | None = None) -> str:
    return Say(
        Text.ROLL_FOOTER,
        BOT_FOOTER=Variables.footerText,
        rolls=Say(Text.ROLL_FOOTER_ROLLS, rolls=rolls, s=Utils.PluralS(rolls)) if rolls is not None else "",
        timestamp=int(time.time()),
    )

def CardBundles(drop: Drop, extras: bool) -> list[Lists.DropBundle]:
    return drop.bundles if extras else [drop.bundle]

def RollCards(drops: list[Drop], extras: bool = True) -> tuple[list[tuple[list, bytes]], dict[int, bytes]]:
    cards, lootCards = [], {}
    for drop in drops:
        cards += [RollCard.Render(bundle.pieces, bundle.info) for bundle in CardBundles(drop, extras)]
        if extras and drop.bonusLoot:
            lootCards[id(drop)] = RollCard.RenderLoot(drop.bonusLoot)
    return cards, lootCards

async def RenderCards(drops: list[Drop], extras: bool = True) -> tuple[list[tuple[list, bytes]], dict[int, bytes]]:
    RollCard.LoadEmojis([bundle for drop in drops for bundle in CardBundles(drop, extras)])
    return await asyncio.to_thread(RollCards, drops, extras)

def ImageGallery(png: bytes, filename: str, alt: str, files: list[discord.File]) -> discord.ui.MediaGallery:
    files.append(discord.File(io.BytesIO(png), filename=filename))
    return discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{filename}", description=alt[:1000]))

def RollCardLayout(
    drops: list[Drop],
    footer: str,
    cards: list[tuple[list, bytes]],
    lootCards: dict[int, bytes],
    extras: bool = True,
    claimable: bool = False,
    expired: bool = False,
    byline: str = "",
) -> tuple[discord.ui.LayoutView, list[discord.File]]:
    targets = [(drop, bundle) for drop in drops for bundle in CardBundles(drop, extras)]
    files: list[discord.File] = []
    blocks = []
    for number, ((drop, bundle), (slots, png)) in enumerate(zip(targets, cards)):
        head = RollBundleHead(drops, drop, bundle, expired)
        if byline:
            head += f"\n{byline}"
        alt = "; ".join(f"{Items.PieceName(piece)} #{piece.hex} rarity {Items.FormatRarity(piece.rarity)}" for _, piece, _ in slots if piece)
        color = discord.Color.greyple() if expired else BundleColor([bundle])
        blocks.append(([discord.ui.TextDisplay(head), ImageGallery(png, f"armor{number}.png", alt, files)], color))

        lootCard = lootCards.get(id(drop))
        if lootCard and bundle is drop.bundles[-1]:
            alt = "; ".join(f"{item} x{count} {Utils.CompactNumber(coins)}" for item, count, coins, _ in drop.bonusLoot)
            blocks.append(([discord.ui.TextDisplay(LootHeader(drop)), ImageGallery(lootCard, f"loot{number}.png", alt, files)], discord.Color.gold()))

    blocks[-1][0].append(discord.ui.TextDisplay(footer))
    view = discord.ui.LayoutView()
    for items, color in blocks:
        view.add_item(discord.ui.Container(*items, accent_colour=color))
    if claimable:
        view.add_item(ClaimRow())
    return view, files

async def Compose(
    drops: list[Drop],
    userID: Utils.MemberID | None = None,
    rolls: int | None = None,
    extras: bool = True,
    claimable: bool = False,
    expired: bool = False,
) -> tuple[discord.ui.LayoutView, list[discord.File]]:
    cards, lootCards = await RenderCards(drops, extras)
    byline = Byline(drops[0], userID) if userID else ""
    return RollCardLayout(drops, Footer(rolls), cards, lootCards, extras, claimable, expired, byline)

def ClaimBuild(drops: list[Drop], userID: Utils.MemberID):
    guildID = drops[0].guildID
    targets = [target for drop in drops for target in drop.bundles]

    def build():
        scope = Profiles.Scope(guildID, userID)
        profile = Profiles.ClaimProfile(guildID, userID)
        sources = [(piece, target) for target in targets for piece in target.pieces]

        for drop in drops:
            hasBonus = random.random() < Upgrades.BonusCoinsChance(profile, guildID)
            drop.bonusCoins = SellValue(guildID, drop.bundle.rarity, setting=Utils.Setting.BONUS_COIN_RATE) if hasBonus else 0
            drop.bonusLoot = Items.RollLoot(drop.bonusCoins)
            Profiles.Earn(profile, "bonus", drop.bonusCoins)
            if hasBonus:
                Profiles.AddStat(profile, "bonus.procs")
            bestKey = "rolled.bestRarity"
            if drop.dropType is not DropType.ROLL:
                bestKey = "claimed.bestRarity"
                Profiles.AddStat(profile, "claims.total")
                Profiles.AddStat(profile, "rolls.total")
                if drop.postedAt:
                    Profiles.MinStat(profile, "claims.fastest", round(time.monotonic() - drop.postedAt, 3))
            for bundle in drop.bundles:
                Profiles.AddStat(profile, "rolled.bundles")
                if IsSpecial(guildID, bundle):
                    Profiles.AddStat(profile, "rolled.special")
                if bundle.void:
                    Profiles.AddStat(profile, "rolled.void", len(bundle.pieces))
                elif bundle is not drop.bundle:
                    Profiles.AddStat(profile, "rolled.bonus")
                for armor in {piece.armor for piece in bundle.pieces}:
                    Profiles.AddStat(profile, f"rolled.armor.{armor}")
                for piece in bundle.pieces:
                    Profiles.AddStat(profile, f"rolled.slot.{piece.slot}")
                    Profiles.MaxStat(profile, bestKey, piece.rarity)

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
            Profiles.AddStat(profile, "rolls.total")
            if len(drops) > 1:
                Profiles.AddStat(profile, "rolls.double")
            if random.random() < Upgrades.FreeRollChance(profile, guildID):
                profile["rolls"] += 1
                Profiles.AddStat(profile, "rolls.free")
        return userUpdates, appUpdates, itemIDs
    return rollBuild, onSuccess

def AnnounceClaim(drop: Drop, userID: Utils.MemberID) -> None:
    if any(IsSpecial(drop.guildID, bundle) for bundle in drop.bundles):
        MainBot.FireAndForget(SendSpecialAlert(drop, userID))

async def SendSpecialAlert(drop: Drop, userID: Utils.MemberID) -> None:
    special = [bundle for bundle in drop.bundles if IsSpecial(drop.guildID, bundle)]
    channelID = Utils.GuildConfig(drop.guildID).get("specialChannelID") or drop.channelID
    if not special or not channelID:
        return
    channel = MainBot.GetClient().get_channel(channelID)
    if channel is None:
        return
    try:
        alert = replace(drop, bundle=special[0], extras=special[1:], bonusCoins=0, bonusLoot=[])
        view, files = await Compose([alert], userID)
        await channel.send(view=view, files=files, allowed_mentions=noMentions)
    except discord.HTTPException:
        pass

async def HandleClaim(interaction: discord.Interaction):
    async def reply(text: str):
        await Logger.SendInteractionMessage(interaction=interaction, message=text, ephemeral=True)

    drop = drops.get(interaction.message.id)
    user = interaction.user
    if drop is None:
        return await reply(Say(Text.CLAIM_GONE))
    if shuttingDown:
        return await reply(Say(Text.CLAIM_SHUTDOWN))
    if drop.state is not DropState.OPEN:
        return await reply(Say(Text.CLAIM_ALREADY_CLAIMED if drop.state is DropState.CLAIMED else Text.CLAIM_IN_PROGRESS))
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
        return await reply(Say(Text.CLAIM_FAILED, reason=reason))

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
            view, files = await Compose(claims, userID, rolls)
            return await interaction.edit_original_response(view=view, attachments=files, allowed_mentions=noMentions)
        except discord.HTTPException as e:
            lastError = e
        if attempt < sendRetries:
            await asyncio.sleep(sendRetryDelaySeconds)
    await Logger.LogHeadlessError(f"Failed to post a roll result in guild {claims[0].guildID}: {lastError}")
    return None

async def PostDrop(channel: Utils.SendableChannel, drop: Drop) -> discord.Message:
    view, files = await Compose([drop], extras=False, claimable=True)
    message = await channel.send(view=view, files=files)
    drop.message = message
    drop.postedAt = time.monotonic()
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
        view, files = await Compose([drop], extras=False, expired=True)
        await drop.message.edit(view=view, attachments=files)
    except discord.HTTPException:
        pass

async def EditClaimed(drop: Drop, userID: Utils.MemberID) -> None:
    try:
        view, files = await Compose([drop], userID)
        await drop.message.edit(view=view, attachments=files, allowed_mentions=noMentions)
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

def DropDelay(guildID: Utils.GuildID) -> float:
    low = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.DROP_INTERVAL_MIN_SECONDS)
    high = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.DROP_INTERVAL_MAX_SECONDS)
    return random.uniform(min(low, high), max(low, high)) / TemporaryBuffs.BeaconMultiplier(guildID, "frequency")

def NextDropTime(guildID: Utils.GuildID, now: float, planned: float | None, lastMultiplier: float | None, multiplier: float) -> float:
    if planned is None:
        return now + DropDelay(guildID)
    if planned > now and lastMultiplier is not None and lastMultiplier != multiplier:
        return now + (planned - now) * lastMultiplier / multiplier
    return planned

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
        channelID = Utils.GuildConfig(guild.id).get("dropChannelID")
        if channelID is None:
            nextDrops.pop(guild.id, None)
            lastBeaconMult.pop(guild.id, None)
            continue
        multiplier = TemporaryBuffs.BeaconMultiplier(guild.id, "frequency")
        nextTick = NextDropTime(guild.id, now, nextDrops.get(guild.id), lastBeaconMult.get(guild.id), multiplier)
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
    results = await asyncio.gather(*(SendTimedDrop(guild, channelID) for guild, channelID in due), return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            await Logger.LogHeadlessError(f"Unexpected error sending timed drop: {result!r}")

def CanPost(channel, me) -> bool:
    permissions = channel.permissions_for(me)
    return permissions.send_messages and permissions.embed_links and permissions.attach_files

async def SendTimedDrop(guild, channelID: Utils.ChannelID) -> None:
    if shuttingDown:
        return
    luck = Utils.GetSettingValueFromGuild(guild.id, Utils.Setting.TIMED_DROP_LUCK) * TemporaryBuffs.BeaconMultiplier(guild.id, "luck")
    drop = await BuildDrop(guild.id, luck, channelID=channelID, dropType=DropType.TIMED)
    if drop is None:
        return
    channel = MainBot.GetClient().get_channel(channelID)
    if channel is None or not CanPost(channel, guild.me):
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
