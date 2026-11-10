import threading
import datetime
import sqlite3
import asyncio
import glob
import json
import os

from Utils import Variables
from Utils import Logger

Deleted = object()
database = None
databaseLock = threading.Lock()
readDatabase = None
readDatabaseLock = threading.Lock()
backupDelaySeconds = 4 * 60 * 60

instanceLockFile = None

def _LockSingleInstance() -> None:
    global instanceLockFile
    lockFile = open(f"{Variables.PERSISTENT_DB_FILE_PATH}.lock", "a")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lockFile.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lockFile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lockFile.close()
        raise RuntimeError("Another bot is already using the database.")
    instanceLockFile = lockFile

def _SplitUserDataBlobs(db) -> None:
    for key, value in db.execute("SELECT key, value FROM data WHERE collection = 'userData' AND key NOT LIKE '%:%'").fetchall():
        for dataType, dataValue in json.loads(value).items():
            db.execute("INSERT OR REPLACE INTO data VALUES ('userData', ?, ?)", (f"{key}:{dataType}", json.dumps(dataValue)))
        db.execute("DELETE FROM data WHERE collection = 'userData' AND key = ?", (key,))

migrations = [_SplitUserDataBlobs]
def _Migrate(db) -> None:
    row = db.execute("SELECT value FROM data WHERE collection = 'meta' AND key = 'schemaVersion'").fetchone()
    version = json.loads(row[0]) if row else 0
    if version > len(migrations):
        raise RuntimeError(f"{Variables.PERSISTENT_DB_FILE_PATH} is schema version {version}, this code only knows {len(migrations)}. Update the bot instead of downgrading.")
    if version < len(migrations) and db.execute("SELECT 1 FROM data LIMIT 1").fetchone():
        BackupDatabase(backupPath=os.path.join(Variables.PERSISTENT_DATA_BACKUPS_PATH, f"Persistent_before-schema-{version + 1}.db.premigration"))
    for target in range(version, len(migrations)):
        db.execute("BEGIN IMMEDIATE")
        try:
            migrations[target](db)
            db.execute("INSERT OR REPLACE INTO data VALUES ('meta', 'schemaVersion', ?)", (json.dumps(target + 1),))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise

async def OpenDatabase() -> None:
    global database, readDatabase
    if database is not None:
        return

    _LockSingleInstance()
    db = sqlite3.connect(Variables.PERSISTENT_DB_FILE_PATH, check_same_thread=False, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS data (collection TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (collection, key)) WITHOUT ROWID")

    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        db.close()
        raise RuntimeError(f"{Variables.PERSISTENT_DB_FILE_PATH} is corrupted, load latest backup.")
    try:
        _Migrate(db)
    except BaseException:
        db.close()
        raise

    readDatabase = sqlite3.connect(Variables.PERSISTENT_DB_FILE_PATH, check_same_thread=False, isolation_level=None)
    readDatabase.execute("PRAGMA query_only=ON")
    database = db

async def LoadCollection(name: str) -> dict:
    with databaseLock:
        rows = database.execute("SELECT key, value FROM data WHERE collection = ?", (name,)).fetchall()
    return {key: json.loads(value) for key, value in rows}

def _ReadPrefix(name: str, prefix: str) -> dict:
    upper = prefix[:-1] + chr(ord(prefix[-1]) + 1)
    with readDatabaseLock:
        rows = readDatabase.execute("SELECT key, value FROM data WHERE collection = ? AND key >= ? AND key < ?", (name, prefix, upper)).fetchall()
    return {key[len(prefix):]: value for key, value in rows}

async def ReadPrefix(name: str, prefix: str) -> dict:
    return await asyncio.to_thread(_ReadPrefix, name, prefix)

async def WriteRows(rows: list) -> None:
    if rows:
        await asyncio.to_thread(_WriteRows, rows)

def _WriteRows(rows: list) -> None:
    with databaseLock:
        database.execute("BEGIN IMMEDIATE")
        try:
            for name, key, serialized in rows:
                if serialized is None:
                    database.execute("DELETE FROM data WHERE collection = ? AND key = ?", (name, key))
                else:
                    database.execute("INSERT OR REPLACE INTO data VALUES (?, ?, ?)", (name, key, serialized))
            database.execute("COMMIT")
        except BaseException:
            if database.in_transaction:
                database.execute("ROLLBACK")
            raise

def _ToRows(name: str, values: dict) -> list:
    return [(name, key, None if value is Deleted else json.dumps(value)) for key, value in values.items()]

async def WriteValues(name: str, values: dict) -> None:
    if values:
        await asyncio.to_thread(WriteValuesBlocking, name, values)

def WriteValuesBlocking(name: str, values: dict) -> None:
    if values:
        _WriteRows(_ToRows(name, values))

def BackupDatabase(keep: int = 12, backupPath: str | None = None) -> None:
    backupPrefix = os.path.join(Variables.PERSISTENT_DATA_BACKUPS_PATH, "Persistent")
    scheduled = backupPath is None
    if scheduled:
        backupPath = f"{backupPrefix}_{datetime.datetime.now().strftime('%Y%m%d%H')}.db.backup"
    if os.path.exists(backupPath):
        return

    tempPath = f"{backupPath}.tmp"
    source = sqlite3.connect(Variables.PERSISTENT_DB_FILE_PATH)
    destination = sqlite3.connect(tempPath)
    try:
        source.backup(destination)
        if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("New backup failed its integrity check, kept the older backups.")
    except BaseException:
        destination.close()
        if os.path.exists(tempPath):
            os.remove(tempPath)
        raise
    finally:
        source.close()
    destination.close()
    os.replace(tempPath, backupPath)
    if scheduled:
        for oldPath in sorted(glob.glob(glob.escape(backupPrefix) + "_*.db.backup"))[:-keep]:
            os.remove(oldPath)

async def BackupLoop():
    while True:
        try:
            await asyncio.to_thread(BackupDatabase)
        except Exception as e:
            await Logger.LogHeadlessError(f"Error in BackupLoop: {e}")
        await asyncio.sleep(backupDelaySeconds)
