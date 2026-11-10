import functools
import aiohttp
import asyncio
import time
import math

from datetime import datetime

from Utils import Logger

_sharedSession: aiohttp.ClientSession | None = None

async def GetSharedSession() -> aiohttp.ClientSession:
    global _sharedSession
    if _sharedSession is None or _sharedSession.closed:
        _sharedSession = aiohttp.ClientSession()
    return _sharedSession

async def CloseSharedSession():
    global _sharedSession
    if _sharedSession is not None and not _sharedSession.closed:
        await _sharedSession.close()
    _sharedSession = None

def GetNowTimestamp():
    return math.floor(datetime.now().timestamp() * 1000)

def MinMaxHexInt(
    hexInt: int
) -> int:
    return min(max(hexInt, 0), 16777215)

def MakeNameSafe(name):
    return Logger.MakeNameSafe(name)

def NormalizeUUID(uuid):
    return uuid.replace("-", "").lower()

def SyncStartCoroutine(coroutine):
    try:
        asyncio.run_coroutine_threadsafe(coroutine, Logger.mainLoop)
    except:
        pass

def OffloadBlocking(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)
    return wrapper

def FormatNumber(number: float, valueType: type = int) -> str:
    if valueType is float:
        return f"{number:,.2f}"
    return f"{int(number):,}"

SI_SYMBOL = ["", "k", "M", "B", "T", "P", "E"]
def CompactNumber(number):
    if number == 0:
        return number

    tier = int(math.log10(abs(number)) / 3)

    if tier == 0:
        return number

    suffix = SI_SYMBOL[tier]
    scale = 10 ** (tier * 3)

    scaled = number / scale
    i = 2
    scaled_f = f"{scaled:.{i}f}"
    length_f = len(scaled_f)
    while scaled_f[length_f - 1:length_f] == "0":
        i -= 1
        scaled_f = f"{scaled:.{i}f}"
        length_f = len(scaled_f)
        if i == 0:
            break

    return f"{scaled:.{i}f}{suffix}"

def UncompactNumber(abbr_number: str) -> float:
    abbrev = abbr_number[-1].lower()
    number_str = abbr_number[:-1]

    multipliers = {
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "t": 1_000_000_000_000,
    }

    multiplier = multipliers.get(abbrev, 1)
    return float(abbr_number) if multiplier == 1 else float(number_str) * multiplier

def TimedFunction(label, fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    print(f"{label}: {time.perf_counter()-t0:.2f}s")
    return result
async def TimedCoroutine(label, coro):
    t0 = time.perf_counter()
    result = await coro
    print(f"{label}: {time.perf_counter()-t0:.2f}s")
    return result
