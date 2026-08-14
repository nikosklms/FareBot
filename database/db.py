import sqlite3
import aiosqlite
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from config import DB_PATH

def init_db(db_path: Optional[str] = None):
    """Synchronously initialize SQLite database tables."""
    target_path = db_path or DB_PATH
    conn = sqlite3.connect(target_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trackers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                origin_code TEXT NOT NULL,
                origin_name TEXT NOT NULL,
                destination_code TEXT NOT NULL,
                destination_name TEXT NOT NULL,
                departure_date TEXT NOT NULL,
                return_date TEXT,
                max_budget REAL NOT NULL,
                currency TEXT DEFAULT 'EUR',
                frequency_hours INTEGER DEFAULT 6,
                direct_only INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ACTIVE',
                consecutive_failures INTEGER DEFAULT 0,
                last_checked_at TIMESTAMP,
                last_price_found REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("ALTER TABLE trackers ADD COLUMN direct_only INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE trackers ADD COLUMN departure_date_end TEXT")
        except sqlite3.OperationalError:
            pass
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracker_id INTEGER NOT NULL,
                price REAL NOT NULL,
                airline TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(tracker_id) REFERENCES trackers(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS unauthorized_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                input_text TEXT,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()

class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def init_db(self):
        """Initialize tables asynchronously according to design spec."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trackers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    origin_code TEXT NOT NULL,
                    origin_name TEXT NOT NULL,
                    destination_code TEXT NOT NULL,
                    destination_name TEXT NOT NULL,
                    departure_date TEXT NOT NULL,
                    departure_date_end TEXT,
                    return_date TEXT,
                    max_budget REAL NOT NULL,
                    currency TEXT DEFAULT 'EUR',
                    frequency_hours INTEGER DEFAULT 6,
                    direct_only INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'ACTIVE',
                    consecutive_failures INTEGER DEFAULT 0,
                    last_checked_at TIMESTAMP,
                    last_price_found REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            try:
                await db.execute("ALTER TABLE trackers ADD COLUMN direct_only INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                await db.execute("ALTER TABLE trackers ADD COLUMN departure_date_end TEXT")
            except sqlite3.OperationalError:
                pass
            await db.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracker_id INTEGER NOT NULL,
                    price REAL NOT NULL,
                    airline TEXT,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(tracker_id) REFERENCES trackers(id) ON DELETE CASCADE
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS unauthorized_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    full_name TEXT,
                    input_text TEXT,
                    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    async def create_tracker(
        self,
        user_id: int,
        origin_code: str,
        origin_name: str,
        destination_code: str,
        destination_name: str,
        departure_date: str,
        max_budget: float,
        return_date: Optional[str] = None,
        frequency_hours: int = 6,
        currency: str = "EUR",
        direct_only: int = 0,
        departure_date_end: Optional[str] = None
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO trackers (
                    user_id, origin_code, origin_name, destination_code, destination_name,
                    departure_date, departure_date_end, return_date, max_budget, frequency_hours, currency, direct_only
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, origin_code, origin_name, destination_code, destination_name,
                departure_date, departure_date_end, return_date, max_budget, frequency_hours, currency, direct_only
            ))
            await db.commit()
            return cursor.lastrowid


    async def get_active_trackers_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM trackers WHERE user_id = ? AND status = 'ACTIVE'",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_active_trackers(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM trackers WHERE status = 'ACTIVE'") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_tracker_by_id(self, tracker_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM trackers WHERE id = ?", (tracker_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_trackers(self, user_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM trackers WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def update_tracker_status(self, tracker_id: int, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trackers SET status = ? WHERE id = ?", (status, tracker_id)
            )
            await db.commit()

    async def update_tracker_budget(self, tracker_id: int, new_budget: float):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trackers SET max_budget = ?, status = 'ACTIVE' WHERE id = ?",
                (new_budget, tracker_id)
            )
            await db.commit()

    async def increment_failure_count(self, tracker_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trackers SET consecutive_failures = consecutive_failures + 1 WHERE id = ?",
                (tracker_id,)
            )
            await db.commit()
            async with db.execute(
                "SELECT consecutive_failures FROM trackers WHERE id = ?", (tracker_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def reset_failure_count(self, tracker_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trackers SET consecutive_failures = 0 WHERE id = ?", (tracker_id,)
            )
            await db.commit()

    async def log_price(self, tracker_id: int, price: float, airline: Optional[str] = None):
        async with aiosqlite.connect(self.db_path) as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "UPDATE trackers SET last_price_found = ?, last_checked_at = ? WHERE id = ?",
                (price, now, tracker_id)
            )
            await db.execute(
                "INSERT INTO price_history (tracker_id, price, airline) VALUES (?, ?, ?)",
                (tracker_id, price, airline)
            )
            await db.commit()

    async def delete_tracker(self, tracker_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM price_history WHERE tracker_id = ?", (tracker_id,))
            await db.execute("DELETE FROM trackers WHERE id = ?", (tracker_id,))
            await db.commit()

    async def get_expired_trackers(self, current_date_str: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM trackers WHERE status = 'ACTIVE' AND departure_date < ?",
                (current_date_str,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def log_unauthorized_attempt(self, user_id: int, username: Optional[str], full_name: Optional[str], input_text: Optional[str]):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO unauthorized_attempts (user_id, username, full_name, input_text) VALUES (?, ?, ?, ?)",
                (user_id, username, full_name, input_text)
            )
            await db.commit()

    async def update_budget(self, tracker_id: int, new_budget: float) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trackers SET max_budget = ? WHERE id = ?",
                (new_budget, tracker_id)
            )
            await db.commit()

    async def has_active_tracker(self, user_id: int, origin_code: str, destination_code: str, departure_date: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM trackers WHERE user_id = ? AND origin_code = ? AND destination_code = ? AND departure_date = ? AND status IN ('ACTIVE', 'PAUSED')",
                (user_id, origin_code, destination_code, departure_date)
            ) as cursor:
                row = await cursor.fetchone()
                return (row[0] > 0) if row else False

    async def has_active_digest(self, user_id: int, origin_code: str, region_code: str, departure_date: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM trackers WHERE user_id = ? AND origin_code = ? AND destination_code = ? AND departure_date = ? AND status IN ('ACTIVE', 'PAUSED')",
                (user_id, origin_code, region_code, departure_date)
            ) as cursor:
                row = await cursor.fetchone()
                return (row[0] > 0) if row else False

    async def purge_stale_trackers(self) -> Dict[str, int]:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        cutoff_60d = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")

        async with aiosqlite.connect(self.db_path) as db:
            # Rule 1: Mark past departure active trackers as EXPIRED
            cursor = await db.execute(
                "UPDATE trackers SET status = 'EXPIRED' WHERE status = 'ACTIVE' AND departure_date < ?",
                (today_str,)
            )
            expired_count = cursor.rowcount

            # Rule 2 & 3: Purge old expired or long-paused trackers
            cursor = await db.execute(
                "DELETE FROM trackers WHERE (status = 'EXPIRED' AND created_at < ?) OR (status = 'PAUSED' AND created_at < ?)",
                (cutoff_30d, cutoff_60d)
            )
            purged_count = cursor.rowcount

            # Cleanup orphan price history
            await db.execute("DELETE FROM price_history WHERE tracker_id NOT IN (SELECT id FROM trackers)")
            await db.commit()

            return {"expired": expired_count, "purged": purged_count}
