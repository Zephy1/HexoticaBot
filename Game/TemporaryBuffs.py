import asyncio
import time

from enum import StrEnum

from Utils.Translation import Say, Text
from Database import PersistentAppData
from Database import Atomic
from Utils import Variables
from Game import Profiles
from Utils import Utils

LUCK_POTION_SECONDS = 30 * 60
BEACON_SECONDS = 60 * 60
BEACON_KINDS = ("luck", "frequency")
CLOCK_KEY = "buffClock"
CLOCK_SAVE_SECONDS = 15

class BuffSetting(StrEnum):
    LUCK_POTION_COST = "luckPotionCost"
    LUCK_POTION_BONUS = "luckPotionBonus"
    BEACON_COST = "beaconCost"
    BEACON_BONUS = "beaconBonus"

BUFF_SETTINGS = {
    BuffSetting.LUCK_POTION_COST:  Variables.GameSetting(Say(Text.SETTING_LUCK_POTION_COST_LABEL), Say(Text.SETTING_LUCK_POTION_COST_DESCRIPTION), 250_000_000, 1, 10_000_000_000, isInt=True),
    BuffSetting.LUCK_POTION_BONUS: Variables.GameSetting(Say(Text.SETTING_LUCK_POTION_BONUS_LABEL), Say(Text.SETTING_LUCK_POTION_BONUS_DESCRIPTION), 1.5, 1.0, 10.0),
    BuffSetting.BEACON_COST:       Variables.GameSetting(Say(Text.SETTING_BEACON_COST_LABEL), Say(Text.SETTING_BEACON_COST_DESCRIPTION), 1_000_000_000, 1, 100_000_000_000, isInt=True),
    BuffSetting.BEACON_BONUS:      Variables.GameSetting(Say(Text.SETTING_BEACON_BONUS_LABEL), Say(Text.SETTING_BEACON_BONUS_DESCRIPTION), 0.5, 0.0, 5.0),
}
Variables.SETTINGS.update(BUFF_SETTINGS)

clockBase = 0.0
clockStart = time.monotonic()

def Clock() -> float:
    return clockBase + time.monotonic() - clockStart

def LoadClock() -> None:
    global clockBase, clockStart
    clockBase = PersistentAppData.PeekData(CLOCK_KEY, 0.0)
    clockStart = time.monotonic()

async def SaveClock() -> None:
    await PersistentAppData.UpdateData(CLOCK_KEY, Clock(), showMessage=False, durable=False)

async def ClockLoop() -> None:
    while True:
        await asyncio.sleep(CLOCK_SAVE_SECONDS)
        await SaveClock()

def WallTime(clockUntil: float) -> float:
    return time.time() + max(0.0, clockUntil - Clock())

def PeekBeacon(
    guildID: Utils.GuildID,
    kind: str,
) -> dict:
    return PersistentAppData.PeekData(f"beacon.{guildID}", {}).get(kind, {})

def CheckBeaconKind(kind: str) -> None:
    if kind not in BEACON_KINDS:
        raise ValueError(Say(Text.BEACON_UNKNOWN, kind=kind))

def LuckPotionMultiplier(
    profile: dict,
    guildID: Utils.GuildID,
) -> float:
    if profile.get("luckClockUntil", 0) > Clock():
        return Utils.GetSettingValueFromGuild(guildID, BuffSetting.LUCK_POTION_BONUS)
    return 1.0

async def BuyLuckPotion(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
) -> tuple[float, Utils.Coins]:
    scope = Profiles.Scope(guildID, userID)
    await Profiles.EnsureProfile(guildID, userID)
    cost = Utils.GetSettingValueFromGuild(guildID, BuffSetting.LUCK_POTION_COST)

    def build():
        profile = Profiles.ClaimProfile(guildID, userID)
        if profile["coins"] < cost:
            raise ValueError(Say(Text.POTION_COST, cost=Utils.CompactNumber(cost), coins=Utils.CompactNumber(profile['coins'])))
        profile["coins"] -= cost
        profile["luckClockUntil"] = max(profile.get("luckClockUntil", 0), Clock()) + LUCK_POTION_SECONDS
        expires = WallTime(profile["luckClockUntil"])
        return Profiles.ProfileUpdate(scope, profile), {}, (expires, cost)

    return await Atomic.AtomicUpdate(guildID, [scope], build, useCommitLock=False)

def LuckPotionRemaining(profile: dict) -> float:
    return max(0.0, profile.get("luckClockUntil", 0) - Clock())

def BeaconStatus(
    guildID: Utils.GuildID,
    kind: str,
) -> tuple[bool, float, Utils.Coins, Utils.Coins]:
    beacon = PeekBeacon(guildID, kind)
    secondsLeft = max(0.0, beacon.get("clockUntil", 0) - Clock())
    cost = Utils.GetSettingValueFromGuild(guildID, BuffSetting.BEACON_COST)
    return secondsLeft > 0, secondsLeft, beacon.get("pool", 0), cost

def BeaconMultiplier(
    guildID: Utils.GuildID,
    kind: str,
) -> float:
    until = PeekBeacon(guildID, kind).get("clockUntil", 0)
    if until > Clock():
        return 1 + Utils.GetSettingValueFromGuild(guildID, BuffSetting.BEACON_BONUS)
    return 1.0

async def FundBeacon(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    kind: str,
    coins: Utils.Coins,
) -> tuple[Utils.Coins, float]:
    CheckBeaconKind(kind)
    Utils.CheckNumber(coins, Say(Text.FIELD_COINS), low=1, isInt=True)
    coins = int(coins)
    scope = Profiles.Scope(guildID, userID)
    await Profiles.EnsureProfile(guildID, userID)
    cost = Utils.GetSettingValueFromGuild(guildID, BuffSetting.BEACON_COST)

    def build():
        profile = Profiles.ClaimProfile(guildID, userID)
        if profile["coins"] < coins:
            raise ValueError(Say(Text.COINS_ONLY, coins=Utils.CompactNumber(profile['coins'])))
        beacons = PersistentAppData.GetData(f"beacon.{guildID}", {})
        beacon = beacons.setdefault(kind, {
            "pool": 0,
        })
        profile["coins"] -= coins
        pending = beacon.setdefault("pending", [])
        pending.append([str(userID), coins])
        runs, beacon["pool"] = divmod(beacon["pool"] + coins, cost)
        if runs:
            beacon["clockUntil"] = max(beacon.get("clockUntil", 0), Clock()) + runs * BEACON_SECONDS
            owed = runs * cost
            while owed and pending:
                if pending[0][1] <= owed:
                    owed -= pending[0][1]
                    pending.pop(0)
                else:
                    pending[0][1] -= owed
                    owed = 0
        appUpdates = {
            f"appData.beacon.{guildID}": beacons,
        }
        expires = WallTime(beacon.get("clockUntil", 0))
        return Profiles.ProfileUpdate(scope, profile), appUpdates, (beacon["pool"], expires)

    return await Atomic.AtomicUpdate(guildID, [scope], build)

async def AdminSetLuckPotion(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    seconds: float,
) -> float:
    Utils.CheckNumber(seconds, Say(Text.FIELD_DURATION))
    scope = Profiles.Scope(guildID, userID)
    await Profiles.EnsureProfile(guildID, userID)

    def build():
        profile = Profiles.CachedProfile(scope)
        if profile is None:
            raise ValueError(Say(Text.NO_PROFILE_USER))
        if seconds > 0:
            profile["luckClockUntil"] = Clock() + seconds
            expires = WallTime(profile["luckClockUntil"])
        else:
            profile["luckClockUntil"] = 0
            expires = 0.0
        return Profiles.ProfileUpdate(scope, profile), {}, expires

    return await Atomic.AtomicUpdate(guildID, [scope], build, useCommitLock=False)

async def AdminClearBeaconPool(
    guildID: Utils.GuildID,
    kind: str,
    refund: bool,
) -> dict[Utils.MemberID, Utils.Coins]:
    CheckBeaconKind(kind)
    pendingSnapshot = PeekBeacon(guildID, kind).get("pending", [])
    for contributor, _ in pendingSnapshot:
        await Profiles.EnsureProfile(guildID, int(contributor))
    scopes = [Profiles.Scope(guildID, int(contributor)) for contributor, _ in pendingSnapshot]

    def build():
        beacons = PersistentAppData.GetData(f"beacon.{guildID}", {})
        beacon = beacons.get(kind, {})
        pool = beacon.get("pool", 0)
        pending = beacon.get("pending", [])
        refunds: dict[Utils.MemberID, Utils.Coins] = {}
        if refund and pool > 0:
            for contributor, coins in pending:
                refunds[int(contributor)] = refunds.get(int(contributor), 0) + coins
            if sum(refunds.values()) != pool:
                raise RuntimeError(f"The {kind} beacon pool does not match its contributions, nothing was changed.")
        appUpdates = {}
        if pool > 0 or pending:
            beacon["pool"] = 0
            beacon["pending"] = []
            beacons[kind] = beacon
            appUpdates[f"appData.beacon.{guildID}"] = beacons
        userUpdates = {}
        for contributorID, share in refunds.items():
            scope = Profiles.Scope(guildID, contributorID)
            profile = Profiles.CachedProfile(scope)
            if profile is None:
                raise RuntimeError(f"The profile of {scope} is not loaded, the beacon pool was not cleared.")
            profile["coins"] += share
            userUpdates[scope] = {
                "profile": profile,
            }
        return userUpdates, appUpdates, refunds

    return await Atomic.AtomicUpdate(guildID, scopes, build)
