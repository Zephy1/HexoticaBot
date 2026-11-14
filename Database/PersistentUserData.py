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

async def GetAllUserData(scope: Utils.UserScope):
    return {dataType: json.loads(row) for dataType, row in (await Read(scope)).items()}
async def GetUserDataType(
    scope: Utils.UserScope,
    dataType: str,
    defaultValue=None,
):
    row = (await Read(scope)).get(dataType)
    return json.loads(row) if row is not None else defaultValue
async def UpdateUserData(
    scope: Utils.UserScope,
    dataType: str,
    newValue,
    nestedDataType: str | None = None,
) -> None:
    await asyncio.shield(Apply(scope, dataType, lambda current: newValue, nestedDataType))
async def ModifyUserData(
    scope: Utils.UserScope,
    dataType: str,
    modifier,
    nestedDataType: str | None = None,
    defaultValue=None,
):
    return await asyncio.shield(Apply(
        scope, dataType,
        lambda current: modifier(current if current is not None else json.loads(json.dumps(defaultValue))),
        nestedDataType,
    ))
async def Apply(
    scope: Utils.UserScope,
    dataType: str,
    modifier,
    nestedDataType: str | None,
):
    async with userLocks[scope]:
        userData = await LoadLocked(scope)
        oldRow = userData.get(dataType)
        root = json.loads(oldRow) if oldRow is not None else None

        if nestedDataType:
            container = root if root is not None else {}
            newValue = modifier(container.get(nestedDataType))
            if newValue is None:
                container.pop(nestedDataType, None)
            else:
                container[nestedDataType] = newValue
            newRoot = container or None
        else:
            newValue = newRoot = modifier(root)

        newRow = None if newRoot is None else await asyncio.to_thread(json.dumps, newRoot)
        if newRow == oldRow:
            return newValue

        await PersistentData.WriteRows([("userData", f"{scope}:{dataType}", newRow)])
        if newRow is None:
            del userData[dataType]
        else:
            userData[dataType] = newRow
        return newValue
