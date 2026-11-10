import collections
import asyncio
import json
import time

from Database import PersistentData

idleEvictSeconds = 15 * 60
evictCheckSeconds = 60

persistentUserData = {}
lastAccess = {}
userLocks = collections.defaultdict(asyncio.Lock)

async def LoadPersistentUserData():
    await PersistentData.OpenDatabase()

async def EvictLoop():
    while True:
        await asyncio.sleep(evictCheckSeconds)
        cutoff = time.monotonic() - idleEvictSeconds
        for userIDString in [key for key, seen in lastAccess.items() if seen < cutoff and not userLocks[key].locked()]:
            persistentUserData.pop(userIDString, None)
            del lastAccess[userIDString]

async def _Load(userIDString: str) -> dict:
    userData = persistentUserData.get(userIDString)
    if userData is None:
        userData = await PersistentData.ReadPrefix("userData", f"{userIDString}:")
        persistentUserData[userIDString] = userData
    lastAccess[userIDString] = time.monotonic()
    return userData

async def _Read(userIDString: str) -> dict:
    userData = persistentUserData.get(userIDString)
    if userData is None:
        async with userLocks[userIDString]:
            return await _Load(userIDString)
    lastAccess[userIDString] = time.monotonic()
    return userData

async def GetAllUserData(userID: int):
    return {dataType: json.loads(row) for dataType, row in (await _Read(str(userID))).items()}
async def GetUserDataType(userID: int, dataType: str, defaultValue=None):
    row = (await _Read(str(userID))).get(dataType)
    return json.loads(row) if row is not None else defaultValue
async def UpdateUserData(
    userID: int,
    dataType: str,
    newValue,
    nestedDataType: str | None = None,
) -> None:
    await asyncio.shield(_Apply(str(userID), dataType, lambda current: newValue, nestedDataType))
async def ModifyUserData(
    userID: int,
    dataType: str,
    modifier,
    nestedDataType: str | None = None,
    defaultValue=None,
):
    return await asyncio.shield(_Apply(
        str(userID), dataType,
        lambda current: modifier(current if current is not None else json.loads(json.dumps(defaultValue))),
        nestedDataType,
    ))
async def _Apply(
    userIDString: str,
    dataType: str,
    modifier,
    nestedDataType: str | None,
):
    async with userLocks[userIDString]:
        userData = await _Load(userIDString)
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

        await PersistentData.WriteRows([("userData", f"{userIDString}:{dataType}", newRow)])
        if newRow is None:
            del userData[dataType]
        else:
            userData[dataType] = newRow
        return newValue
