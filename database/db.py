import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

import aiosqlite

from database.models import ACTIVE, APPROVED, EXPIRED, PAUSED, PENDING, WEEKDAYS, Digest, Tracker, User

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3

TRACKERS_DDL = """
CREATE TABLE {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    origin_code TEXT NOT NULL,
    destination_code TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    departure_date_end TEXT,
    max_budget REAL NOT NULL,
    frequency_hours INTEGER NOT NULL DEFAULT 6,
    direct_only INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_checked_at TIMESTAMP,
    last_price_found REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

DIGESTS_DDL = """
CREATE TABLE digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    origin_code TEXT NOT NULL,
    region TEXT NOT NULL,
    max_budget REAL,
    days_ahead INTEGER,
    departure_date TEXT,
    departure_date_end TEXT,
    sort_mode TEXT NOT NULL DEFAULT 'both',
    delivery_day TEXT NOT NULL DEFAULT 'Sunday',
    delivery_time TEXT NOT NULL DEFAULT '15:00',
    max_results INTEGER NOT NULL DEFAULT 10,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

PRICE_HISTORY_DDL = """
CREATE TABLE {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    price REAL NOT NULL,
    airline TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

USERS_DDL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    status TEXT NOT NULL,
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP
)
"""

TRACKER_COLUMNS = [
    "id", "user_id", "origin_code", "destination_code", "departure_date", "departure_date_end",
    "max_budget", "frequency_hours", "direct_only", "status", "consecutive_failures",
    "last_checked_at", "last_price_found", "created_at",
]

TRACKER_EDITABLE = {"departure_date", "departure_date_end", "direct_only", "max_budget", "frequency_hours", "status",
                    "consecutive_failures"}
# Changing these means a different search, so earlier prices no longer apply.
TRACKER_SEARCH_FIELDS = {"departure_date", "departure_date_end", "direct_only"}
DIGEST_EDITABLE = {"max_budget", "days_ahead", "departure_date", "departure_date_end", "sort_mode",
                   "delivery_day", "delivery_time", "max_results", "status"}

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


EXPIRED_KEPT_DAYS = 30


@dataclass
class StaleCleanup:
    """What purge_stale changed; expired items were active or paused until now."""
    expired_trackers: list[Tracker]
    expired_digests: list[Digest]
    purged: int


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _tracker(row: aiosqlite.Row) -> Tracker:
    data = dict(row)
    data["direct_only"] = bool(data["direct_only"])
    return Tracker(**data)


def _digest(row: aiosqlite.Row) -> Digest:
    return Digest(**dict(row))


class Database:
    def __init__(self, path: str):
        self.path = path

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.path, timeout=15.0) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def migrate(self) -> None:
        """Bring the database file up to SCHEMA_VERSION."""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("PRAGMA user_version") as cur:
                version = (await cur.fetchone())[0]
            if version >= SCHEMA_VERSION:
                return
            if version < 1:
                await _migrate_to_v1(conn)
            if version < 2:
                await conn.execute(USERS_DDL)
            if version < 3:
                # Access requests in the users table replaced the log of unauthorized attempts.
                await conn.execute("DROP TABLE IF EXISTS unauthorized_attempts")
            await conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            await conn.commit()
            logger.info("Database migrated to schema version %d", SCHEMA_VERSION)

    # ------------------------------------------------------------------
    # Trackers
    # ------------------------------------------------------------------

    async def create_tracker(
        self,
        user_id: int,
        origin_code: str,
        destination_code: str,
        departure_date: str,
        max_budget: float,
        departure_date_end: Optional[str] = None,
        frequency_hours: int = 6,
        direct_only: bool = False,
    ) -> Tracker:
        async with self._connect() as db:
            cur = await db.execute(
                "INSERT INTO trackers (user_id, origin_code, destination_code, departure_date,"
                " departure_date_end, max_budget, frequency_hours, direct_only)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, origin_code, destination_code, departure_date,
                 departure_date_end, max_budget, frequency_hours, int(direct_only)),
            )
            await db.commit()
            tracker_id = cur.lastrowid
        return await self.get_tracker(tracker_id)

    async def get_tracker(self, tracker_id: int) -> Optional[Tracker]:
        async with self._connect() as db:
            async with db.execute("SELECT * FROM trackers WHERE id = ?", (tracker_id,)) as cur:
                row = await cur.fetchone()
        return _tracker(row) if row else None

    async def list_trackers(self, user_id: int) -> list[Tracker]:
        async with self._connect() as db:
            async with db.execute(
                "SELECT * FROM trackers WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user_id,)
            ) as cur:
                return [_tracker(r) for r in await cur.fetchall()]

    async def active_trackers(self) -> list[Tracker]:
        async with self._connect() as db:
            async with db.execute("SELECT * FROM trackers WHERE status = ?", (ACTIVE,)) as cur:
                return [_tracker(r) for r in await cur.fetchall()]

    async def find_tracker(
        self, user_id: int, origin_code: str, destination_code: str, departure_date: str,
        departure_date_end: Optional[str] = None, direct_only: bool = False,
    ) -> Optional[Tracker]:
        """An existing active or paused tracker for the same route, dates and flight type."""
        async with self._connect() as db:
            async with db.execute(
                "SELECT * FROM trackers WHERE user_id = ? AND origin_code = ? AND destination_code = ?"
                " AND departure_date = ? AND departure_date_end IS ? AND direct_only = ?"
                " AND status IN (?, ?) LIMIT 1",
                (user_id, origin_code, destination_code, departure_date, departure_date_end, int(direct_only),
                 ACTIVE, PAUSED),
            ) as cur:
                row = await cur.fetchone()
        return _tracker(row) if row else None

    async def set_tracker_status(self, tracker_id: int, status: str) -> None:
        await self._execute("UPDATE trackers SET status = ? WHERE id = ?", (status, tracker_id))

    async def update_tracker(self, tracker_id: int, **changes: Any) -> Optional[Tracker]:
        """Change editable fields and return the updated tracker.

        A new date window or flight type clears the last price, which was for the old search.
        """
        before = await self.get_tracker(tracker_id)
        search_changed = before and any(getattr(before, field) != changes[field]
                                        for field in TRACKER_SEARCH_FIELDS & set(changes))
        if "direct_only" in changes:
            changes["direct_only"] = int(changes["direct_only"])
        await self._update("trackers", TRACKER_EDITABLE, tracker_id, changes)
        if search_changed:
            await self._execute("UPDATE trackers SET last_price_found = NULL, last_checked_at = NULL WHERE id = ?",
                                (tracker_id,))
        return await self.get_tracker(tracker_id)

    async def delete_tracker(self, tracker_id: int) -> None:
        await self._execute("DELETE FROM trackers WHERE id = ?", (tracker_id,))

    async def record_price(self, tracker_id: int, price: float, airline: Optional[str]) -> None:
        """Store a successful check: price history row, last price, failure counter reset."""
        async with self._connect() as db:
            await db.execute(
                "UPDATE trackers SET last_price_found = ?, last_checked_at = ?, consecutive_failures = 0"
                " WHERE id = ?",
                (price, _now(), tracker_id),
            )
            await db.execute(
                "INSERT INTO price_history (tracker_id, price, airline) VALUES (?, ?, ?)",
                (tracker_id, price, airline),
            )
            await db.commit()

    async def record_no_flights(self, tracker_id: int) -> None:
        """A check that worked but found no matching flights."""
        await self._execute(
            "UPDATE trackers SET last_price_found = NULL, last_checked_at = ?, consecutive_failures = 0 WHERE id = ?",
            (_now(), tracker_id),
        )

    async def record_failure(self, tracker_id: int) -> int:
        """Count a failed check and return the consecutive failure total."""
        async with self._connect() as db:
            await db.execute(
                "UPDATE trackers SET consecutive_failures = consecutive_failures + 1, last_checked_at = ?"
                " WHERE id = ?",
                (_now(), tracker_id),
            )
            await db.commit()
            async with db.execute("SELECT consecutive_failures FROM trackers WHERE id = ?", (tracker_id,)) as cur:
                row = await cur.fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Digests
    # ------------------------------------------------------------------

    async def create_digest(
        self,
        user_id: int,
        origin_code: str,
        region: str,
        max_budget: Optional[float] = None,
        days_ahead: Optional[int] = None,
        departure_date: Optional[str] = None,
        departure_date_end: Optional[str] = None,
        sort_mode: str = "both",
        delivery_day: str = "Sunday",
        delivery_time: str = "15:00",
        max_results: int = 10,
    ) -> Digest:
        async with self._connect() as db:
            cur = await db.execute(
                "INSERT INTO digests (user_id, origin_code, region, max_budget, days_ahead, departure_date,"
                " departure_date_end, sort_mode, delivery_day, delivery_time, max_results)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, origin_code, region, max_budget, days_ahead, departure_date,
                 departure_date_end, sort_mode, delivery_day, delivery_time, max_results),
            )
            await db.commit()
            digest_id = cur.lastrowid
        return await self.get_digest(digest_id)

    async def get_digest(self, digest_id: int) -> Optional[Digest]:
        async with self._connect() as db:
            async with db.execute("SELECT * FROM digests WHERE id = ?", (digest_id,)) as cur:
                row = await cur.fetchone()
        return _digest(row) if row else None

    async def list_digests(self, user_id: int) -> list[Digest]:
        async with self._connect() as db:
            async with db.execute(
                "SELECT * FROM digests WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user_id,)
            ) as cur:
                return [_digest(r) for r in await cur.fetchall()]

    async def active_digests(self) -> list[Digest]:
        async with self._connect() as db:
            async with db.execute("SELECT * FROM digests WHERE status = ?", (ACTIVE,)) as cur:
                return [_digest(r) for r in await cur.fetchall()]

    async def find_digest(
        self,
        user_id: int,
        origin_code: str,
        region: str,
        days_ahead: Optional[int],
        departure_date: Optional[str],
        departure_date_end: Optional[str],
        max_budget: Optional[float] = None,
        sort_mode: str = "both",
        delivery_day: str = "Sunday",
        delivery_time: str = "15:00",
    ) -> Optional[Digest]:
        """An existing active or paused digest with exactly the same settings."""
        async with self._connect() as db:
            async with db.execute(
                "SELECT * FROM digests WHERE user_id = ? AND origin_code = ? AND region = ?"
                " AND days_ahead IS ? AND departure_date IS ? AND departure_date_end IS ? AND max_budget IS ?"
                " AND sort_mode = ? AND delivery_day = ? AND delivery_time = ? AND status IN (?, ?) LIMIT 1",
                (user_id, origin_code, region, days_ahead, departure_date, departure_date_end, max_budget,
                 sort_mode, delivery_day, delivery_time, ACTIVE, PAUSED),
            ) as cur:
                row = await cur.fetchone()
        return _digest(row) if row else None

    async def set_digest_status(self, digest_id: int, status: str) -> None:
        await self._execute("UPDATE digests SET status = ? WHERE id = ?", (status, digest_id))

    async def update_digest(self, digest_id: int, **changes: Any) -> Optional[Digest]:
        """Change editable fields and return the updated digest."""
        await self._update("digests", DIGEST_EDITABLE, digest_id, changes)
        return await self.get_digest(digest_id)

    async def delete_digest(self, digest_id: int) -> None:
        await self._execute("DELETE FROM digests WHERE id = ?", (digest_id,))

    # ------------------------------------------------------------------
    # Shared
    # ------------------------------------------------------------------

    async def count_active(self, user_id: int) -> int:
        """Active trackers plus active digests, for the per-user limit."""
        async with self._connect() as db:
            async with db.execute(
                "SELECT (SELECT COUNT(*) FROM trackers WHERE user_id = ? AND status = ?)"
                " + (SELECT COUNT(*) FROM digests WHERE user_id = ? AND status = ?)",
                (user_id, ACTIVE, user_id, ACTIVE),
            ) as cur:
                return (await cur.fetchone())[0]

    # ------------------------------------------------------------------
    # Users (access requests)
    # ------------------------------------------------------------------

    async def request_access(self, user_id: int, username: Optional[str], full_name: Optional[str]) -> bool:
        """Record a pending request. Returns False if this user already asked (or was decided on)."""
        async with self._connect() as db:
            cur = await db.execute(
                "INSERT OR IGNORE INTO users (user_id, username, full_name, status) VALUES (?, ?, ?, ?)",
                (user_id, username, full_name, PENDING),
            )
            await db.commit()
            return cur.rowcount == 1

    async def get_user(self, user_id: int) -> Optional[User]:
        async with self._connect() as db:
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
        return User(**dict(row)) if row else None

    async def list_users(self) -> list[User]:
        async with self._connect() as db:
            async with db.execute("SELECT * FROM users ORDER BY requested_at, user_id") as cur:
                return [User(**dict(row)) for row in await cur.fetchall()]

    async def is_approved(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user and user.status == APPROVED)

    async def set_user_status(self, user_id: int, status: str) -> None:
        await self._execute("UPDATE users SET status = ?, decided_at = ? WHERE user_id = ?",
                            (status, _now(), user_id))

    async def delete_user(self, user_id: int) -> None:
        """Forget a user entirely, so they can ask for access again."""
        await self._execute("DELETE FROM users WHERE user_id = ?", (user_id,))

    async def purge_stale(self, today: date) -> StaleCleanup:
        """Expire trackers and fixed-date digests whose travel dates have passed, and delete
        expired ones 30 days after their last travel date. Paused items with future dates
        and rolling digests are never removed automatically.
        """
        today_str = today.isoformat()
        delete_before = (today - timedelta(days=EXPIRED_KEPT_DAYS)).isoformat()
        last_date = "COALESCE(departure_date_end, departure_date)"

        async with self._connect() as db:
            async with db.execute(
                f"SELECT * FROM trackers WHERE status IN (?, ?) AND {last_date} < ?", (ACTIVE, PAUSED, today_str)
            ) as cur:
                trackers = [_tracker(r) for r in await cur.fetchall()]
            async with db.execute(
                f"SELECT * FROM digests WHERE status IN (?, ?) AND days_ahead IS NULL AND {last_date} < ?",
                (ACTIVE, PAUSED, today_str),
            ) as cur:
                digests = [_digest(r) for r in await cur.fetchall()]
            for table, items in (("trackers", trackers), ("digests", digests)):
                await db.executemany(f"UPDATE {table} SET status = ? WHERE id = ?", [(EXPIRED, i.id) for i in items])

            purged = 0
            for table in ("trackers", "digests"):
                cur = await db.execute(
                    f"DELETE FROM {table} WHERE status = ? AND {last_date} < ?", (EXPIRED, delete_before)
                )
                purged += cur.rowcount
            await db.commit()

        return StaleCleanup(expired_trackers=trackers, expired_digests=digests, purged=purged)

    async def _update(self, table: str, editable: set[str], row_id: int, changes: dict[str, Any]) -> None:
        unknown = set(changes) - editable
        if unknown:
            raise ValueError(f"Not editable in {table}: {', '.join(sorted(unknown))}")
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            await self._execute(f"UPDATE {table} SET {assignments} WHERE id = ?", (*changes.values(), row_id))

    async def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        async with self._connect() as db:
            await db.execute(sql, params)
            await db.commit()


# ----------------------------------------------------------------------
# Migration from the pre-versioned schema
# ----------------------------------------------------------------------

async def _table_exists(conn: aiosqlite.Connection, name: str) -> bool:
    async with conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)) as cur:
        return await cur.fetchone() is not None


async def _migrate_to_v1(conn: aiosqlite.Connection) -> None:
    """Create the v1 schema, converting a legacy database in place if one exists.

    Legacy databases kept digests in the trackers table (destination_code
    'REGION:<NAME>') with their settings packed into departure_date in
    several historical formats. Those rows move to the digests table with
    their ids preserved; plain trackers are copied as-is.
    """
    await conn.execute("PRAGMA foreign_keys = OFF")

    if not await _table_exists(conn, "trackers"):
        await conn.execute(TRACKERS_DDL.format(name="trackers"))
        await conn.execute(DIGESTS_DDL)
        await conn.execute(PRICE_HISTORY_DDL.format(name="price_history"))
        return

    await conn.execute(TRACKERS_DDL.format(name="trackers_v1"))
    await conn.execute(DIGESTS_DDL)
    await conn.execute(PRICE_HISTORY_DDL.format(name="price_history_v1"))

    async with conn.execute("SELECT * FROM trackers") as cur:
        legacy_rows = [dict(r) for r in await cur.fetchall()]

    for row in legacy_rows:
        if str(row.get("destination_code", "")).startswith("REGION:"):
            digest = _digest_from_legacy(row)
            columns = ", ".join(digest)
            await conn.execute(
                f"INSERT INTO digests ({columns}) VALUES ({', '.join('?' for _ in digest)})",
                tuple(digest.values()),
            )
        else:
            tracker = {col: row.get(col) for col in TRACKER_COLUMNS}
            tracker["frequency_hours"] = tracker["frequency_hours"] or 6
            tracker["direct_only"] = tracker["direct_only"] or 0
            tracker["status"] = tracker["status"] or ACTIVE
            tracker["consecutive_failures"] = tracker["consecutive_failures"] or 0
            await conn.execute(
                f"INSERT INTO trackers_v1 ({', '.join(TRACKER_COLUMNS)})"
                f" VALUES ({', '.join('?' for _ in TRACKER_COLUMNS)})",
                tuple(tracker[col] for col in TRACKER_COLUMNS),
            )

    if await _table_exists(conn, "price_history"):
        await conn.execute(
            "INSERT INTO price_history_v1 (id, tracker_id, price, airline, checked_at)"
            " SELECT id, tracker_id, price, airline, checked_at FROM price_history"
            " WHERE tracker_id IN (SELECT id FROM trackers_v1)"
        )
        await conn.execute("DROP TABLE price_history")

    await conn.execute("DROP TABLE trackers")
    await conn.execute("ALTER TABLE trackers_v1 RENAME TO trackers")
    await conn.execute("ALTER TABLE price_history_v1 RENAME TO price_history")
    logger.info("Converted legacy database: %d rows migrated", len(legacy_rows))


def _digest_from_legacy(row: dict[str, Any]) -> dict[str, Any]:
    packed = str(row.get("departure_date") or "")
    start = None
    end = row.get("departure_date_end")
    days = row.get("timeframe_days")
    sort_mode = row.get("sort_mode") or "both"
    schedule = row.get("delivery_schedule")

    window = packed
    if "|" in packed:
        parts = packed.split("|")
        window = parts[0]
        if len(parts) >= 3:
            sort_mode = parts[1]
        schedule = schedule or parts[-1]
    elif "@" in packed:
        schedule = schedule or packed
        window = ""

    if ".." in window:
        start, end = window.split("..", 1)
    elif window.endswith("d") and window[:-1].isdigit():
        days = int(window[:-1])
    elif window.isdigit():
        days = int(window)
    elif ISO_DATE.match(window):
        start = window

    if start is None:
        end = None
        days = days or 30
    else:
        days = None

    day, time = _parse_schedule(schedule)
    budget = row.get("max_budget") or None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "origin_code": row["origin_code"],
        "region": row["destination_code"].split(":", 1)[1].lower(),
        "max_budget": budget,
        "days_ahead": days,
        "departure_date": start,
        "departure_date_end": end,
        "sort_mode": sort_mode if sort_mode in ("discount", "price", "both") else "both",
        "delivery_day": day,
        "delivery_time": time,
        "max_results": row.get("max_results") or 10,
        "status": row.get("status") or ACTIVE,
        "created_at": row.get("created_at"),
    }


def _parse_schedule(schedule: Optional[str]) -> tuple[str, str]:
    """'Friday@18:00' -> ('Friday', '18:00'), falling back to Sunday 15:00."""
    day, time = "Sunday", "15:00"
    if schedule and "@" in schedule:
        raw_day, raw_time = schedule.split("@", 1)
        day = next((d for d in WEEKDAYS if d.lower() == raw_day.strip().lower()), day)
        match = CLOCK.match(raw_time.strip())
        if match:
            time = f"{int(match.group(1)):02d}:{match.group(2)}"
    return day, time
