import sqlite3

from database.db import SCHEMA_VERSION, Database

# The trackers table as it existed before versioned migrations, with every optional column.
LEGACY_SCHEMA = """
CREATE TABLE trackers (
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
    status TEXT DEFAULT 'ACTIVE',
    consecutive_failures INTEGER DEFAULT 0,
    last_checked_at TIMESTAMP,
    last_price_found REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    direct_only INTEGER DEFAULT 0,
    departure_date_end TEXT,
    timeframe_days INTEGER,
    sort_mode TEXT,
    delivery_schedule TEXT,
    max_results INTEGER DEFAULT 10
);
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL,
    price REAL NOT NULL,
    airline TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tracker_id) REFERENCES trackers(id) ON DELETE CASCADE
);
CREATE TABLE unauthorized_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    full_name TEXT,
    input_text TEXT,
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def legacy_db(path, rows):
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    for row in rows:
        columns = ", ".join(row)
        conn.execute(f"INSERT INTO trackers ({columns}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))
    conn.execute("INSERT INTO price_history (tracker_id, price, airline) VALUES (1, 99.0, 'Aegean')")
    conn.execute("INSERT INTO unauthorized_attempts (user_id, input_text) VALUES (5, '/start')")
    conn.commit()
    conn.close()


def row(id, destination, departure_date, **extra):
    return {"id": id, "user_id": 1, "origin_code": "ATH", "origin_name": "Athens", "destination_code": destination,
            "destination_name": "x", "departure_date": departure_date, "max_budget": extra.pop("max_budget", 80.0),
            **extra}


async def test_fresh_database_gets_current_schema(tmp_path):
    db = Database(str(tmp_path / "new.db"))
    await db.migrate()
    await db.migrate()

    conn = sqlite3.connect(db.path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"trackers", "digests", "price_history", "users"} <= tables
    assert "unauthorized_attempts" not in tables


async def test_legacy_database_is_converted(tmp_path):
    path = str(tmp_path / "legacy.db")
    legacy_db(path, [
        row(1, "LON", "2027-03-15", departure_date_end="2027-03-20", direct_only=1, last_price_found=99.0),
        row(2, "REGION:EUROPE", "RELATIVE", timeframe_days=90, sort_mode="price",
            delivery_schedule="Friday@18:00", max_results=5),
        row(3, "REGION:ASIA", "60d|discount|Monday@09:30", max_budget=0.0),
        row(4, "REGION:LATIN_AMERICA", "30d|Sunday@15:00"),
        row(5, "REGION:AFRICA", "2027-02-01..2027-02-10|both|Tuesday@07:05"),
        row(6, "REGION:OCEANIA", "Saturday@21:00"),
        row(7, "REGION:MIDDLE_EAST", "2027-04-04"),
    ])

    db = Database(path)
    await db.migrate()

    tracker = await db.get_tracker(1)
    assert (tracker.origin_code, tracker.destination_code) == ("ATH", "LON")
    assert (tracker.departure_date, tracker.departure_date_end) == ("2027-03-15", "2027-03-20")
    assert tracker.direct_only is True and tracker.last_price_found == 99.0
    assert await db.get_tracker(2) is None

    def summary(d):
        return (d.region, d.days_ahead, d.departure_date, d.departure_date_end, d.sort_mode,
                d.delivery_day, d.delivery_time, d.max_results, d.max_budget)

    assert summary(await db.get_digest(2)) == ("europe", 90, None, None, "price", "Friday", "18:00", 5, 80.0)
    assert summary(await db.get_digest(3)) == ("asia", 60, None, None, "discount", "Monday", "09:30", 10, None)
    assert summary(await db.get_digest(4)) == ("latin_america", 30, None, None, "both", "Sunday", "15:00", 10, 80.0)
    assert summary(await db.get_digest(5)) == ("africa", None, "2027-02-01", "2027-02-10", "both", "Tuesday", "07:05", 10, 80.0)
    assert summary(await db.get_digest(6)) == ("oceania", 30, None, None, "both", "Saturday", "21:00", 10, 80.0)
    assert summary(await db.get_digest(7)) == ("middle_east", None, "2027-04-04", None, "both", "Sunday", "15:00", 10, 80.0)

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT tracker_id, price FROM price_history").fetchall() == [(1, 99.0)]
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'unauthorized_attempts'").fetchall()
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


async def test_new_rows_after_migration_get_fresh_ids(tmp_path):
    path = str(tmp_path / "legacy.db")
    legacy_db(path, [row(1, "LON", "2027-03-15"), row(9, "REGION:EUROPE", "RELATIVE", timeframe_days=30)])
    db = Database(path)
    await db.migrate()

    tracker = await db.create_tracker(user_id=1, origin_code="SKG", destination_code="PAR",
                                      departure_date="2027-05-01", max_budget=50.0)
    digest = await db.create_digest(user_id=1, origin_code="SKG", region="asia", days_ahead=30)
    assert tracker.id == 2
    assert digest.id == 10


def version_and_trackers(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0], conn.execute("SELECT COUNT(*) FROM trackers").fetchone()[0]
    finally:
        conn.close()


async def test_migrating_backs_up_the_database_first(tmp_path):
    path = str(tmp_path / "farebot.db")
    db = Database(path)
    await db.migrate()
    await db.create_tracker(user_id=1, origin_code="ATH", destination_code="LON", departure_date="2027-03-15",
                            max_budget=80.0)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    await db.migrate()

    assert version_and_trackers(path + ".v2.bak") == (2, 1)
    assert version_and_trackers(path) == (SCHEMA_VERSION, 1)


async def test_an_existing_backup_is_never_overwritten(tmp_path):
    path = str(tmp_path / "farebot.db")
    db = Database(path)
    await db.migrate()
    sqlite3.connect(path + ".v2.bak").close()  # left by an earlier attempt that failed halfway
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    await db.migrate()

    assert sqlite3.connect(path + ".v2.bak").execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0


async def test_new_and_up_to_date_databases_are_not_backed_up(tmp_path):
    path = str(tmp_path / "farebot.db")
    db = Database(path)
    await db.migrate()  # new and empty
    await db.migrate()  # already current
    assert sorted(p.name for p in tmp_path.iterdir()) == ["farebot.db"]


async def test_legacy_databases_are_backed_up_too(tmp_path):
    path = str(tmp_path / "legacy.db")
    legacy_db(path, [row(1, "LON", "2027-03-15")])
    await Database(path).migrate()
    assert version_and_trackers(path + ".v0.bak") == (0, 1)


async def test_a_backup_that_failed_halfway_is_redone(tmp_path, monkeypatch):
    import aiosqlite
    import pytest
    path = str(tmp_path / "farebot.db")
    db = Database(path)
    await db.migrate()
    await db.create_tracker(user_id=1, origin_code="ATH", destination_code="LON", departure_date="2027-03-15",
                            max_budget=80.0)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    async def disk_full(self, target, **kwargs):
        await target.execute("CREATE TABLE half_written (x)")
        await target.commit()
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(aiosqlite.Connection, "backup", disk_full)
        with pytest.raises(OSError):
            await db.migrate()
    assert version_and_trackers(path)[0] == 2  # nothing migrated without a backup

    await db.migrate()
    assert version_and_trackers(path + ".v2.bak") == (2, 1)
    assert version_and_trackers(path) == (SCHEMA_VERSION, 1)
    assert not (tmp_path / "farebot.db.v2.bak.partial").exists()


async def test_a_migration_that_fails_halfway_changes_nothing_and_can_be_retried(tmp_path, monkeypatch):
    import pytest
    import database.db as db_module
    path = str(tmp_path / "legacy.db")
    legacy_db(path, [row(1, "LON", "2027-03-15"), row(2, "REGION:EUROPE", "RELATIVE", timeframe_days=90)])

    def crash(row):
        raise RuntimeError("power cut")

    with monkeypatch.context() as patch:
        patch.setattr(db_module, "_digest_from_legacy", crash)  # fails after the new tables were created
        with pytest.raises(RuntimeError):
            await Database(path).migrate()

    conn = sqlite3.connect(path)
    tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "trackers_v1" not in tables and "digests" not in tables  # nothing half-done was left
    conn.close()

    db = Database(path)
    await db.migrate()  # the next start simply tries again
    assert (await db.get_tracker(1)).destination_code == "LON"
    assert (await db.get_digest(2)).region == "europe"
