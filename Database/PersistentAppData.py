import threading
import asyncio
import json
import copy

from typing import Any

from Database import PersistentData
from Utils import Logger

persistentAppData: dict[str, Any] = {}
dirtyRows: dict[str, str | None] = {}
lock = threading.Lock()
flushLock = threading.Lock()
flushDelaySeconds = 1

def Set(
    key,
    value,
    showMessage: bool = False,
):
    serialized = json.dumps(value)
    persistentAppData[key] = json.loads(serialized)
    dirtyRows[key] = serialized
    if showMessage:
        print(f"Saved {key}: {value}")

def FlushNow():
    with flushLock:
        with lock:
            rows = dict(dirtyRows)
            dirtyRows.clear()
        if not rows:
            return
        try:
            PersistentData.WriteRowsBlocking([("appData", key, serialized) for key, serialized in rows.items()])
        except BaseException:
            with lock:
                for key, serialized in rows.items():
                    dirtyRows.setdefault(key, serialized)
            raise
async def Flush():
    await asyncio.to_thread(FlushNow)
async def FlushLoop():
    while True:
        await asyncio.sleep(flushDelaySeconds)
        if not dirtyRows:
            continue
        try:
            await Flush()
        except Exception as e:
            await Logger.LogHeadlessError(f"Error in FlushLoop: {e}")
            await asyncio.sleep(60)

async def LoadPersistentAppData():
    global persistentAppData
    await PersistentData.OpenDatabase()
    persistentAppData = await PersistentData.LoadCollection("appData")
    return persistentAppData

def GetData(key, defaultValue=None):
    with lock:
        return copy.deepcopy(persistentAppData.get(key, defaultValue))
def PeekData(key, defaultValue=None):
    return persistentAppData.get(key, defaultValue)
async def UpdateData(
    key,
    newValueData,
    showMessage: bool,
    durable: bool = True,
):
    with lock:
        Set(key, newValueData, showMessage)
    if durable:
        await Flush()
async def DeleteData(
    key,
    showMessage: bool,
    durable: bool = True,
):
    with lock:
        persistentAppData.pop(key, None)
        dirtyRows[key] = None
    if durable:
        await Flush()
    if showMessage:
        print(f"Deleted {key}")
