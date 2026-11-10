import threading
import asyncio
import json
import copy

from Database import PersistentData
from Utils import Variables
from Utils import Logger

persistentAppData = {}
dirtyRows = {}
lock = threading.Lock()
flushLock = threading.Lock()
flushDelaySeconds = 1

def _Set(key, value, showMessage: bool = False):
    serialized = json.dumps(value)
    persistentAppData[key] = json.loads(serialized)
    dirtyRows[key] = serialized
    if showMessage:
        print(f"Saved {key}: {value}")

class PersistentAppData:
    key = None
    @classmethod
    def CheckKey(cls):
        if cls.key is None:
            raise NotImplementedError("Subclasses must define a 'key' attribute.")

    @classmethod
    def GetData(cls, defaultValue=None):
        cls.CheckKey()
        with lock:
            return copy.deepcopy(persistentAppData.get(cls.key, defaultValue))

    @classmethod
    async def Update(cls, newValueData, durable: bool = True):
        cls.CheckKey()
        with lock:
            _Set(cls.key, newValueData, True)
        if durable:
            await Flush()

class BotPersonalityData(PersistentAppData):
    key = "botPersonality"
    @classmethod
    async def Update(cls, newValueData, durable: bool = True):
        with lock:
            currentData = persistentAppData.get(cls.key, {})

            _Set("lastBotPersonality", {
                "username": currentData.get("username", Variables.defaultBotName),
                "description": currentData.get("description", Variables.defaultBotDescription),
                "status": currentData.get("status", Variables.defaultBotStatus),
            }, True)

            defaults = {
                "username": Variables.defaultBotName,
                "description": Variables.defaultBotDescription,
                "status": Variables.defaultBotStatus,
            }

            if not currentData:
                finalData = {
                    field: (
                        newValueData.get(field)
                        if newValueData.get(field) is not None
                        else defaults[field]
                    )
                    for field in defaults
                }
            else:
                finalData = currentData.copy()
                for field, value in newValueData.items():
                    if value is not None:
                        finalData[field] = value

            _Set(cls.key, finalData, True)
        if durable:
            await Flush()

def _FlushNow():
    with flushLock:
        with lock:
            rows = dict(dirtyRows)
            dirtyRows.clear()
        if not rows:
            return
        try:
            PersistentData._WriteRows([("appData", key, serialized) for key, serialized in rows.items()])
        except BaseException:
            with lock:
                for key, serialized in rows.items():
                    dirtyRows.setdefault(key, serialized)
            raise
async def Flush():
    await asyncio.to_thread(_FlushNow)
async def FlushLoop():
    while True:
        await asyncio.sleep(flushDelaySeconds)
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
async def UpdateData(key, newValueData, showMessage: bool, durable: bool = True):
    with lock:
        _Set(key, newValueData, showMessage)
    if durable:
        await Flush()
async def DeleteData(key, showMessage: bool, durable: bool = True):
    with lock:
        persistentAppData.pop(key, None)
        dirtyRows[key] = None
    if durable:
        await Flush()
    if showMessage:
        print(f"Deleted {key}")
