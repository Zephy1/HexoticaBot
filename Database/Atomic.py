import contextlib
import asyncio
import inspect
import json

from collections.abc import Iterable

from Database import PersistentUserData
from Database import PersistentAppData
from Database import PersistentData
from Utils import Utils

commitLockWaitSeconds = 5
commitLocks: dict[Utils.GuildID, asyncio.Lock] = {}
commitsInFlight = 0
idle = asyncio.Event()
idle.set()

def CommitLock(guildID: Utils.GuildID) -> asyncio.Lock:
    return commitLocks.setdefault(guildID, asyncio.Lock())

async def WaitCommitsIdle(timeout: float) -> bool:
    try:
        await asyncio.wait_for(idle.wait(), timeout)
        return True
    except TimeoutError:
        return False

def Serialize(value) -> str | None:
    return None if value is None else json.dumps(value)

def ApplyRow(
    cache: dict,
    key: str,
    serialized: str | None,
    *,
    decode: bool = False,
) -> None:
    if serialized is None:
        cache.pop(key, None)
    else:
        cache[key] = json.loads(serialized) if decode else serialized

async def AtomicUpdate(
    guildID: Utils.GuildID | None,
    userScopes: Iterable[Utils.UserScope],
    build,
    useCommitLock: bool = True,
    onSuccess=None,
):
    global commitsInFlight
    async with contextlib.AsyncExitStack() as stack:
        if useCommitLock:
            lock = CommitLock(guildID)
            async with asyncio.timeout(commitLockWaitSeconds):
                await lock.acquire()
            stack.callback(lock.release)
        for scope in sorted({str(s) for s in userScopes}):
            await stack.enter_async_context(PersistentUserData.userLocks[scope])
            await PersistentUserData.LoadLocked(scope)

        built = build()
        if inspect.isawaitable(built):
            built = await built
        userUpdates, appUpdates, result = built

        userRows = {}
        for scope, updates in userUpdates.items():
            cache = PersistentUserData.persistentUserData.get(scope, {})
            serialized = {dataType: Serialize(value) for dataType, value in updates.items()}
            userRows[scope] = {dataType: row for dataType, row in serialized.items() if cache.get(dataType) != row}
        rows = [
            ("userData", f"{scope}:{dataType}", serialized)
            for scope, updates in userRows.items()
            for dataType, serialized in updates.items()
        ]
        appDataUpdates = {}
        for fullKey, value in appUpdates.items():
            collection, _, key = fullKey.partition(".")
            serialized = Serialize(value)
            rows.append((collection, key, serialized))
            if collection == "appData":
                appDataUpdates[key] = serialized

        commitsInFlight += 1
        idle.clear()
        try:
            await PersistentData.WriteRows(rows)
        finally:
            commitsInFlight -= 1
            if not commitsInFlight:
                idle.set()

        for scope, updates in userRows.items():
            cache = PersistentUserData.persistentUserData.setdefault(scope, {})
            for dataType, serialized in updates.items():
                ApplyRow(cache, dataType, serialized)
        if appDataUpdates:
            with PersistentAppData.lock:
                for key, serialized in appDataUpdates.items():
                    ApplyRow(PersistentAppData.persistentAppData, key, serialized, decode=True)
                    PersistentAppData.dirtyRows.pop(key, None)
        if onSuccess is not None:
            onSuccess()
        return result

async def ModifyUserData(
    scope: Utils.UserScope,
    dataType: str,
    modifier,
    defaultValue=None,
):
    def build():
        row = PersistentUserData.persistentUserData[scope].get(dataType)
        newValue = modifier(json.loads(row if row is not None else json.dumps(defaultValue)))
        return {scope: {dataType: newValue}}, {}, newValue

    return await asyncio.shield(AtomicUpdate(None, [scope], build, useCommitLock=False))
