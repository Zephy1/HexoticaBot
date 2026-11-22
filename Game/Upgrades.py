import dataclasses

from Utils.Translation import Say, Text
from Database import PersistentAppData
from Database import Atomic
from Game import Profiles
from Utils import Utils

BASE_CARRYOVER = 0.5
MAX_CARRYOVER = 0.95
MAX_EARNING_SLOTS = 10
INT_UPGRADE_FIELDS = ("baseCost", "maxLevel")

@dataclasses.dataclass(frozen=True, slots=True)
class Upgrade:
    label: str
    description: str
    perLevel: float
    baseCost: int
    growth: float
    maxLevel: int | None = None

    def Cost(self, level: int) -> int:
        return int(self.baseCost * self.growth ** level + 0.5)

UPGRADES = {
    "luck":     Upgrade(Say(Text.UPGRADE_LUCK_LABEL), Say(Text.UPGRADE_LUCK_DESCRIPTION), perLevel=0.05, baseCost=50_000_000, growth=1.29, maxLevel=16),
    "rolls":    Upgrade(Say(Text.UPGRADE_ROLLS_LABEL), Say(Text.UPGRADE_ROLLS_DESCRIPTION), perLevel=1, baseCost=75_000_000, growth=1.3825, maxLevel=15),
    "showcase": Upgrade(Say(Text.UPGRADE_SHOWCASE_SLOTS_LABEL), Say(Text.UPGRADE_SHOWCASE_SLOTS_DESCRIPTION), perLevel=1, baseCost=200_000_000, growth=2.0, maxLevel=8),
    "carryover":  Upgrade(Say(Text.UPGRADE_CARRYOVER_LABEL), Say(Text.UPGRADE_CARRYOVER_DESCRIPTION), perLevel=0.025, baseCost=20_000_000, growth=1.2, maxLevel=10),
    "freeroll":   Upgrade(Say(Text.UPGRADE_FREEROLL_LABEL), Say(Text.UPGRADE_FREEROLL_DESCRIPTION), perLevel=0.02, baseCost=100_000_000, growth=1.35, maxLevel=15),
    "doubleroll": Upgrade(Say(Text.UPGRADE_DOUBLEROLL_LABEL), Say(Text.UPGRADE_DOUBLEROLL_DESCRIPTION), perLevel=0.02, baseCost=400_000_000, growth=1.4, maxLevel=10),
    "haggler":    Upgrade(Say(Text.UPGRADE_HAGGLER_LABEL), Say(Text.UPGRADE_HAGGLER_DESCRIPTION), perLevel=0.05, baseCost=150_000_000, growth=1.35, maxLevel=15),
    "prospector": Upgrade(Say(Text.UPGRADE_PROSPECTOR_LABEL), Say(Text.UPGRADE_PROSPECTOR_DESCRIPTION), perLevel=0.02, baseCost=100_000_000, growth=1.3, maxLevel=15),
    "income":     Upgrade(Say(Text.UPGRADE_INCOME_LABEL), Say(Text.UPGRADE_INCOME_DESCRIPTION), perLevel=0.25, baseCost=120_000_000, growth=1.35, maxLevel=12),
}
DEFAULT_LIMITS = {
    "perLevel": (0, 1),
    "baseCost": (1, 1_000_000_000),
    "growth": (1.0, 5.0),
    "maxLevel": (0, 50),
}
LIMIT_OVERRIDES = {
    "luck": {
        "perLevel": (0, 0.25),
    },
    "rolls": {
        "perLevel": (0, 5),
    },
    "showcase": {
        "perLevel": (0, 3),
        "maxLevel": (0, 10),
    },
    "carryover": {
        "perLevel": (0, 0.05),
    },
    "freeroll": {
        "perLevel": (0, 0.1),
    },
    "doubleroll": {
        "perLevel": (0, 0.1),
    },
    "haggler": {
        "perLevel": (0, 0.25),
    },
    "prospector": {
        "perLevel": (0, 0.05),
    },
    "income": {
        "perLevel": (0, 2),
    },
}
UPGRADE_LIMITS = {
    key: {
        **DEFAULT_LIMITS,
        **LIMIT_OVERRIDES.get(key, {}),
    }
    for key in UPGRADES
}
COMPOUNDING_UPGRADES = ("luck", "haggler")

def CheckUpgrade(upgrade: str) -> None:
    if upgrade not in UPGRADES:
        raise ValueError(Say(Text.UPGRADE_UNKNOWN, upgrade=upgrade))

def GetUpgrade(
    guildID: Utils.GuildID,
    key: str,
) -> Upgrade:
    overrides = Utils.GuildConfig(guildID).get("upgrades", {}).get(key, {})
    changes = {}
    for field, (low, high) in UPGRADE_LIMITS[key].items():
        value = overrides.get(field)
        if isinstance(value, (int, float)):
            value = min(max(value, low), high)
            changes[field] = int(value + 0.5) if field in INT_UPGRADE_FIELDS else value
    return dataclasses.replace(UPGRADES[key], **changes)

async def SetUpgradeOverride(
    guildID: Utils.GuildID,
    key: str,
    field: str,
    value: float | None,
) -> None:
    if key not in UPGRADE_LIMITS or field not in UPGRADE_LIMITS[key]:
        raise ValueError(Say(Text.UPGRADE_UNKNOWN_FIELD, key=key, field=field))
    if value is not None:
        Utils.CheckNumber(value, field, *UPGRADE_LIMITS[key][field], isInt=field in INT_UPGRADE_FIELDS)
    config = PersistentAppData.GetData(f"guildConfig.{guildID}", {})
    overrides = config.setdefault("upgrades", {}).setdefault(key, {})
    if value is None:
        overrides.pop(field, None)
    else:
        overrides[field] = value
    await PersistentAppData.UpdateData(f"guildConfig.{guildID}", config, showMessage=False)

def Level(
    profile: dict,
    key: str,
) -> int:
    return profile["upgrades"].get(key, 0)

def EffectiveLevel(
    profile: dict,
    definition: Upgrade,
    key: str,
) -> int:
    level = Level(profile, key)
    return level if definition.maxLevel is None else min(level, definition.maxLevel)

def Add(
    profile: dict,
    guildID: Utils.GuildID,
    key: str,
) -> float:
    definition = GetUpgrade(guildID, key)
    return definition.perLevel * EffectiveLevel(profile, definition, key)

def Compound(
    profile: dict,
    guildID: Utils.GuildID,
    key: str,
) -> float:
    definition = GetUpgrade(guildID, key)
    return (1 + definition.perLevel) ** EffectiveLevel(profile, definition, key)

def CarryoverFraction(
    profile: dict,
    guildID: Utils.GuildID,
) -> float:
    return min(MAX_CARRYOVER, BASE_CARRYOVER + Add(profile, guildID, "carryover"))

def FreeRollChance(
    profile: dict,
    guildID: Utils.GuildID,
) -> float:
    return min(1.0, Add(profile, guildID, "freeroll"))

def DoubleRollChance(
    profile: dict,
    guildID: Utils.GuildID,
) -> float:
    return min(1.0, Add(profile, guildID, "doubleroll"))

def SellMultiplier(
    profile: dict,
    guildID: Utils.GuildID,
) -> float:
    return Compound(profile, guildID, "haggler")

def BonusCoinsChance(
    profile: dict,
    guildID: Utils.GuildID,
) -> float:
    baseChance = Utils.GetSettingValueFromGuild(guildID, Utils.Setting.BONUS_COINS_CHANCE)
    return min(1.0, baseChance + Add(profile, guildID, "prospector"))

def UpgradeCost(
    profile: dict,
    guildID: Utils.GuildID,
    upgrade: str,
) -> Utils.Coins | None:
    level = Level(profile, upgrade)
    definition = GetUpgrade(guildID, upgrade)
    if definition.maxLevel is not None and level >= definition.maxLevel:
        return None
    return definition.Cost(level)

def UpgradeSummary(
    profile: dict,
    guildID: Utils.GuildID,
) -> list[tuple[str, int, int | None, Utils.Coins | None, float]]:
    rows = []
    for key in UPGRADES:
        if key in COMPOUNDING_UPGRADES:
            effect = Compound(profile, guildID, key)
        else:
            effect = Add(profile, guildID, key)
        definition = GetUpgrade(guildID, key)
        cost = UpgradeCost(profile, guildID, key)
        rows.append((definition.label, Level(profile, key), definition.maxLevel, cost, effect))
    return rows

async def ModifyUpgradeProfile(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    upgrade: str,
    change,
):
    CheckUpgrade(upgrade)
    scope = Profiles.Scope(guildID, userID)
    await Profiles.EnsureProfile(guildID, userID)

    def build():
        profile = Profiles.ClaimProfile(guildID, userID)
        return Profiles.ProfileUpdate(scope, profile), {}, change(profile, GetUpgrade(guildID, upgrade))

    return await Atomic.AtomicUpdate(guildID, [scope], build, useCommitLock=False)

async def AdminSetUpgradeLevel(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    upgrade: str,
    level: int,
) -> int:
    CheckUpgrade(upgrade)
    if not isinstance(level, int) or isinstance(level, bool) or level < 0:
        raise ValueError(Say(Text.UPGRADE_LEVEL_INVALID))
    definition = GetUpgrade(guildID, upgrade)
    if definition.maxLevel is not None and level > definition.maxLevel:
        raise ValueError(Say(Text.UPGRADE_CAPS, label=definition.label, maxLevel=definition.maxLevel))

    def change(profile: dict, _: Upgrade) -> int:
        profile["upgrades"][upgrade] = level
        return level

    return await ModifyUpgradeProfile(guildID, userID, upgrade, change)

async def RefundUpgrade(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    upgrade: str,
) -> tuple[int, Utils.Coins]:
    def change(profile: dict, definition: Upgrade) -> tuple[int, Utils.Coins]:
        level = Level(profile, upgrade)
        if level < 1:
            raise ValueError(Say(Text.UPGRADE_NO_LEVELS, label=definition.label))
        newLevel = level - 1
        refund = definition.Cost(newLevel)

        Profiles.Refund(profile, "upgrades", refund)
        profile["upgrades"][upgrade] = newLevel
        return newLevel, refund

    return await ModifyUpgradeProfile(guildID, userID, upgrade, change)

async def BuyUpgrade(
    guildID: Utils.GuildID,
    userID: Utils.MemberID,
    upgrade: str,
) -> tuple[int, Utils.Coins]:
    def change(profile: dict, definition: Upgrade) -> tuple[int, Utils.Coins]:
        cost = UpgradeCost(profile, guildID, upgrade)
        if cost is None:
            raise ValueError(Say(Text.UPGRADE_MAXED, label=definition.label))
        if profile["coins"] < cost:
            raise ValueError(Say(Text.UPGRADE_COST, label=definition.label, cost=Utils.CompactNumber(cost), coins=Utils.CompactNumber(profile['coins'])))

        Profiles.Spend(profile, "upgrades", cost)
        profile["upgrades"][upgrade] = Level(profile, upgrade) + 1
        return profile["upgrades"][upgrade], cost

    return await ModifyUpgradeProfile(guildID, userID, upgrade, change)
