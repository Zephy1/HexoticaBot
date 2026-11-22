import asyncio
import json
import math
import time

from collections.abc import Iterable

from Database import PersistentUserData
from Utils.Translation import Say, Text
from Database import PersistentData
from Game import TemporaryBuffs
from Game import Upgrades
from Utils import Utils

MAX_REFILL_STEPS = 64

def Scope(guildID: Utils.GuildID, userID: Utils.MemberID) -> Utils.UserScope:
    return f"{guildID}-{userID}"

def ProfileUpdate(scope: Utils.UserScope, profile: dict) -> dict:
    return {scope: {"profile": profile}}

def DefaultProfile(guildID: Utils.GuildID) -> dict:
    return {
        "rolls": Utils.GetSettingValueFromGuild(guildID, Utils.Setting.BASE_ROLLS_PER_HOUR),
        "lastRefillHour": Utils.CurrentHour(),
        "coins": 0,
        "since": int(time.time()),
        "upgrades": dict.fromkeys(Upgrades.UPGRADES, 0),
        "showcase": {},
        "earning": [],
    }

def CachedProfile(scope: Utils.UserScope) -> dict | None:
    row = PersistentUserData.persistentUserData.get(scope, {}).get("profile")
    return None if row is None else json.loads(row)

async def AddRolls(
    userData: dict,
    scope: Utils.UserScope,
    rows: list,
    amount: int,
    key: str = "rolls",
) -> str | None:
    row = userData.get("profile")
    if row is None:
        return None
    profile = json.loads(row)
    profile[key] = profile.get(key, 0) + amount
    row = await asyncio.to_thread(json.dumps, profile)
    rows.append(("userData", f"{scope}:profile", row))
    return row

def PeriodIDs() -> dict[str, int]:
    days = Utils.CurrentHour() // 24
    now = time.gmtime()
    return {"day": days, "week": (days + 3) // 7, "month": now.tm_year * 12 + now.tm_mon}

def StatBuckets(profile: dict) -> list[dict]:
    buckets = [profile.setdefault("stats", {})]
    periods = profile.setdefault("periods", {})
    for name, periodID in PeriodIDs().items():
        if periods.get(name, {}).get("id") != periodID:
            periods[name] = {"id": periodID, "stats": {}}
        buckets.append(periods[name]["stats"])
    return buckets

def PeriodStats(profile: dict, period: str) -> dict:
    if period == "all":
        return profile.get("stats", {})
    bucket = profile.get("periods", {}).get(period)
    return bucket["stats"] if bucket and bucket["id"] == PeriodIDs()[period] else {}

def AddStat(profile: dict, key: str, amount: float = 1) -> None:
    if amount:
        for stats in StatBuckets(profile):
            stats[key] = max(0, stats.get(key, 0) + amount)

def MaxStat(profile: dict, key: str, value: float) -> None:
    for stats in StatBuckets(profile):
        stats[key] = max(stats.get(key, 0), value)

def MinStat(profile: dict, key: str, value: float) -> None:
    for stats in StatBuckets(profile):
        stats[key] = min(stats.get(key, value), value)

def Earn(profile: dict, source: str, coins: Utils.Coins) -> None:
    profile["coins"] += coins
    AddStat(profile, "coins.gained", coins)
    AddStat(profile, f"coins.from.{source}", coins)
    MaxStat(profile, "coins.peak", profile["coins"])

def Spend(profile: dict, sink: str, coins: Utils.Coins) -> None:
    profile["coins"] -= coins
    AddStat(profile, "coins.spent", coins)
    AddStat(profile, f"coins.on.{sink}", coins)

def Refund(profile: dict, sink: str, coins: Utils.Coins) -> None:
    profile["coins"] += coins
    AddStat(profile, "coins.spent", -coins)
    AddStat(profile, f"coins.on.{sink}", -coins)
    MaxStat(profile, "coins.peak", profile["coins"])

def TotalRolls(profile: dict) -> int:
    return profile["rolls"] + profile.get("bonusRolls", 0)

async def HeldRolls(scope: Utils.UserScope) -> int:
    held = await PersistentData.ReadRow("pendingRoll", scope)
    return 0 if held is None else int(held)

async def HoldRoll(guildID: Utils.GuildID, userID: Utils.MemberID) -> tuple[dict, bool] | None:
    scope = Scope(guildID, userID)
    async with PersistentUserData.userLocks[scope]:
        userData = await PersistentUserData.LoadLocked(scope)
        row = userData.get("profile")
        profile = json.loads(row) if row is not None else DefaultProfile(guildID)
        ApplyRefill(profile, guildID, scope)
        bonus = profile["rolls"] < 1
        if bonus and profile.get("bonusRolls", 0) < 1:
            return None
        profile["bonusRolls" if bonus else "rolls"] -= 1
        row = await asyncio.to_thread(json.dumps, profile)
        held = await HeldRolls(scope)
        await PersistentData.WriteRows([
            ("userData", f"{scope}:profile", row),
            ("pendingRoll", scope, json.dumps(held + 1)),
        ])
        userData["profile"] = row
        return profile, bonus

async def ReleaseRoll(guildID: Utils.GuildID, userID: Utils.MemberID, bonus: bool = False) -> None:
    scope = Scope(guildID, userID)
    async with PersistentUserData.userLocks[scope]:
        userData = await PersistentUserData.LoadLocked(scope)
        held = await HeldRolls(scope)
        if held < 1:
            return
        rows = [("pendingRoll", scope, None if held == 1 else json.dumps(held - 1))]
        profileRow = await AddRolls(userData, scope, rows, 1, "bonusRolls" if bonus else "rolls")
        await PersistentData.WriteRows(rows)
        if profileRow is not None:
            userData["profile"] = profileRow

async def RecoverPendingRolls() -> None:
    for scope, pending in (await PersistentData.LoadCollection("pendingRoll")).items():
        async with PersistentUserData.userLocks[scope]:
            userData = await PersistentUserData.LoadLocked(scope)
            rows = [("pendingRoll", scope, None)]
            profileRow = await AddRolls(userData, scope, rows, int(pending))
            await PersistentData.WriteRows(rows)
            if profileRow is not None:
                userData["profile"] = profileRow

def EffectiveBaseRolls(profile: dict, guildID: Utils.GuildID) -> int:
    baseRolls = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.BASE_ROLLS_PER_HOUR)
    return baseRolls + int(Upgrades.Add(profile, guildID, "rolls"))

def RollCeiling(
    profile: dict,
    guildID: Utils.GuildID,
    base: int | None = None,
) -> int:
    if base is None:
        base = EffectiveBaseRolls(profile, guildID)
    overflow = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.BASE_ROLL_OVERFLOW)
    multiplier = 1 + overflow + Upgrades.Add(profile, guildID, "carryover")
    return math.ceil(round(base * multiplier, 6))

def RollerLuck(profile: dict, guildID: Utils.GuildID) -> float:
    baseLuck = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.ROLL_BASE_LUCK)
    upgradeLuck = Upgrades.Compound(profile, guildID, "luck")
    potionLuck = TemporaryBuffs.LuckPotionMultiplier(profile, guildID)
    return baseLuck * upgradeLuck * potionLuck

def ShowcaseIncome(
    profile: dict,
    guildID: Utils.GuildID,
    scope: Utils.UserScope,
) -> Utils.Coins:
    rows = PersistentUserData.persistentUserData.get(scope, {})
    rarity = sum(
        max(json.loads(rows[f"item.{itemID}"])["rarity"], 0)
        for slot in ActiveSlots(profile, guildID)
        for itemID in profile["showcase"][str(slot)]
        if f"item.{itemID}" in rows
    )
    rate = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.SHOWCASE_INCOME_RATE)
    bonus = 1 + Upgrades.Add(profile, guildID, "income")
    return int(rarity * rate * bonus + 0.5)

def EarningCapacity(profile: dict, guildID: Utils.GuildID) -> int:
    startingSlots = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.STARTING_EARNING_SHOWCASE_SLOTS)
    extraSlots = int(Upgrades.Add(profile, guildID, "showcase"))
    return min(Upgrades.MAX_EARNING_SLOTS, startingSlots + extraSlots)

def ActiveSlots(profile: dict, guildID: Utils.GuildID) -> list[Utils.SlotIndex]:
    filled = [slot for slot in profile["earning"] if profile["showcase"].get(str(slot))]
    return filled[:EarningCapacity(profile, guildID)]

def SetEarningSlots(profile: dict, guildID: Utils.GuildID, slots: list[Utils.SlotIndex]) -> None:
    slotCount = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.STARTING_SHOWCASE_SLOTS)
    for slot in slots:
        if not 1 <= slot <= slotCount:
            raise ValueError(Say(Text.SHOWCASE_SLOT_RANGE, max=slotCount))
        if not profile["showcase"].get(str(slot)):
            raise ValueError(Say(Text.SHOWCASE_SLOT_EMPTY, slot=slot))
    picked = list(dict.fromkeys(slots))
    capacity = EarningCapacity(profile, guildID)
    if len(picked) > capacity:
        raise ValueError(Say(Text.SHOWCASE_TOO_MANY, max=capacity))
    profile["earning"] = picked

def Unshowcase(profile: dict, itemIDs: Iterable[Utils.ItemID]) -> None:
    gone = set(itemIDs)
    showcase = profile["showcase"]
    for slot in list(showcase):
        showcase[slot] = [itemID for itemID in showcase[slot] if itemID not in gone]
        if not showcase[slot]:
            del showcase[slot]
    profile["earning"] = [slot for slot in profile["earning"] if str(slot) in showcase]

def SetShowcase(
    profile: dict,
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    layout: dict[Utils.SlotIndex, list[Utils.ItemID]],
    earning: list[Utils.SlotIndex],
) -> None:
    slotCount = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.STARTING_SHOWCASE_SLOTS)
    rows = PersistentUserData.persistentUserData.get(Scope(guildID, userID), {})
    showcase: dict[str, list[Utils.ItemID]] = {}
    used: set[Utils.ItemID] = set()
    for slot, itemIDs in sorted(layout.items()):
        if not itemIDs:
            continue
        if not 1 <= slot <= slotCount:
            raise ValueError(Say(Text.SHOWCASE_SLOT_RANGE, max=slotCount))
        if used.intersection(itemIDs) or len(set(itemIDs)) < len(itemIDs) or any(f"item.{itemID}" not in rows for itemID in itemIDs):
            raise ValueError(Say(Text.SHOWCASE_PIECES_GONE))
        pieces = [json.loads(rows[f"item.{itemID}"]) for itemID in itemIDs]
        armors = {str(piece["armor"]) for piece in pieces}
        if len(armors) > 1 and not armors <= Utils.THREE_PIECE:
            raise ValueError(Say(Text.SHOWCASE_MIXED_ARMOR))
        if len({str(piece["slot"]) for piece in pieces}) < len(pieces):
            raise ValueError(Say(Text.SHOWCASE_DUPLICATE_PIECE))
        used.update(itemIDs)
        showcase[str(slot)] = list(itemIDs)
    profile["showcase"] = showcase
    SetEarningSlots(profile, guildID, [slot for slot in earning if str(slot) in showcase])

async def EditShowcase(guildID: Utils.GuildID, userID: Utils.MemberID, edit) -> None:
    scope = Scope(guildID, userID)

    def modify(current: dict | None) -> dict:
        profile = current if current is not None else DefaultProfile(guildID)
        ApplyRefill(profile, guildID, scope)
        edit(profile)
        return profile

    await PersistentUserData.ModifyUserData(scope, "profile", modify)

def ApplyRefill(
    profile: dict,
    guildID: Utils.GuildID,
    scope: Utils.UserScope | None = None,
) -> bool:
    if "since" not in profile:
        rows = PersistentUserData.persistentUserData.get(scope, {})
        profile["since"] = min((json.loads(row)["claimedAt"] for key, row in rows.items() if key.startswith("item.")), default=int(time.time()))
    nowHour = Utils.CurrentHour()
    hours = nowHour - profile["lastRefillHour"]
    if hours <= 0:
        return False
    steps = min(hours, MAX_REFILL_STEPS)
    if scope is not None:
        if scope not in PersistentUserData.persistentUserData:
            raise RuntimeError(f"ApplyRefill called before the user data of {scope} was loaded.")
        Earn(profile, "income", hours * ShowcaseIncome(profile, guildID, scope))
    base = EffectiveBaseRolls(profile, guildID)
    ceiling = RollCeiling(profile, guildID, base)
    carryover = Upgrades.CarryoverFraction(profile, guildID)
    for _ in range(steps):
        refreshed = min(ceiling, base + math.ceil(round(profile["rolls"] * carryover, 6)))
        if refreshed == profile["rolls"]:
            break
        profile["rolls"] = refreshed
    profile["lastRefillHour"] = nowHour
    return True

async def EnsureProfile(guildID: Utils.GuildID, userID: Utils.MemberID) -> dict:
    scope = Scope(guildID, userID)

    def refill(current: dict | None) -> dict:
        profile = current if current is not None else DefaultProfile(guildID)
        ApplyRefill(profile, guildID, scope)
        return profile

    return await PersistentUserData.ModifyUserData(scope, "profile", refill)

async def PeekProfile(guildID: Utils.GuildID, userID: Utils.MemberID) -> dict | None:
    scope = Scope(guildID, userID)
    profile = await PersistentUserData.GetUserDataType(scope, "profile")
    if profile is not None:
        ApplyRefill(profile, guildID, scope)
    return profile

def ClaimProfile(guildID: Utils.GuildID, userID: Utils.MemberID) -> dict:
    scope = Scope(guildID, userID)
    profile = CachedProfile(scope) or DefaultProfile(guildID)
    ApplyRefill(profile, guildID, scope)
    return profile
