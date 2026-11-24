import collections
import asyncio
import json
import time

from Database import PersistentData
from Utils import Utils

idleEvictSeconds = 15 * 60
evictCheckSeconds = 60

persistentUserData: dict[Utils.UserScope, dict[str, str]] = {}
lastAccess: dict[Utils.UserScope, float] = {}
userLocks = collections.defaultdict(asyncio.Lock)

async def LoadPersistentUserData():
    await PersistentData.OpenDatabase()

async def EvictLoop():
    while True:
        await asyncio.sleep(evictCheckSeconds)
        cutoff = time.monotonic() - idleEvictSeconds
        for scope in [key for key, seen in lastAccess.items() if seen < cutoff and not userLocks[key].locked()]:
            persistentUserData.pop(scope, None)
            userLocks.pop(scope, None)
            del lastAccess[scope]

async def LoadLocked(scope: Utils.UserScope) -> dict:
    userData = persistentUserData.get(scope)
    if userData is None:
        userData = await PersistentData.ReadPrefix("userData", f"{scope}:")
        persistentUserData[scope] = userData
    lastAccess[scope] = time.monotonic()
    return userData

async def Read(scope: Utils.UserScope) -> dict:
    userData = persistentUserData.get(scope)
    if userData is None:
        async with userLocks[scope]:
            return await LoadLocked(scope)
    lastAccess[scope] = time.monotonic()
    return userData

async def GetUserDataType(
    scope: Utils.UserScope,
    dataType: str,
    defaultValue=None,
):
    row = (await Read(scope)).get(dataType)
    return json.loads(row) if row is not None else defaultValue
