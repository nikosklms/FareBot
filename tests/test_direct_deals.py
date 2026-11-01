"""Explores and digests can search direct flights only, like /search and /track."""
import sqlite3

from bot.handlers.share import parse_payload, share_payload
from daemon.scheduler import send_digest
from database.db import SCHEMA_VERSION, Database
from providers.base import FlightOffer
from tests.fakes import USER_ID, future
from tests.test_share import digest


def offers(origin, destination, day):
    if destination != "FCO":
        return []
    return [FlightOffer(origin, destination, day, price=40.0, airline="Air", is_direct=True),
            FlightOffer(origin, destination, day, price=25.0, airline="Air", is_direct=False)]


async def test_explore_shortcut_searches_direct_flights_only(bot, provider):
    provider.offers = offers
    await bot.send("/explore ATH europe 2 0 5 direct")
    await bot.finish_background_task()

    assert provider.queries and all(direct for _, _, _, direct in provider.queries)
    report = bot.telegram.last_text
    assert "direct only" in report and "€40.00" in report and "€25.00" not in report
    await bot.press("deals:show", message_id=bot.telegram.last_message_id)
    assert bot.telegram.button_data("Track #1").endswith(":1")  # the tracker watches direct flights too


async def test_explore_wizard_asks_which_flights(bot, provider):
    provider.offers = offers
    await bot.send("/explore")
    for step in ("exp:org:ATH", "exp:reg:europe", "exp:sort:price", "exp:when:days:2"):
        await bot.press(step)
    assert "Which flights" in bot.telegram.last_text
    await bot.press("exp:direct:1")
    assert "Direct flights only" in bot.telegram.last_text
    await bot.press("exp:lim:5")
    await bot.finish_background_task()
    assert all(direct for _, _, _, direct in provider.queries)


async def test_a_direct_digest_searches_direct_flights_only(bot, provider):
    provider.offers = offers
    await bot.send("/digest ATH europe 2 direct")
    [created] = await bot.services.db.list_digests(USER_ID)
    assert created.direct_only and "Direct flights only" in bot.telegram.last_text

    await send_digest(bot.services, bot.app.bot, created.id)
    assert provider.queries and all(direct for _, _, _, direct in provider.queries)
    assert "direct only" in bot.telegram.last_text and "€25.00" not in bot.telegram.last_text


async def test_the_same_digest_with_other_flights_isnt_a_duplicate(bot):
    await bot.send("/digest ATH europe 30")
    await bot.send("/digest ATH europe 30 direct")
    assert {d.direct_only for d in await bot.services.db.list_digests(USER_ID)} == {False, True}
    await bot.send("/digest ATH europe 30 direct")
    assert "already have this digest" in bot.telegram.last_text


async def test_editing_a_digests_flights(bot):
    created = await bot.services.db.create_digest(USER_ID, "ATH", "europe", days_ahead=30)
    await bot.press(f"dash:edit:d:{created.id}")
    await bot.press("edit:field:flights")
    await bot.press("edit:direct:1")
    assert (await bot.services.db.get_digest(created.id)).direct_only
    assert "Direct flights only" in bot.telegram.last_text


def test_share_links_carry_direct_flights_without_getting_longer():
    any_flights, direct = share_payload(digest()), share_payload(digest(direct_only=True))
    assert len(direct) == len(any_flights)
    assert parse_payload(direct)[1]["direct_only"] and not parse_payload(any_flights)[1]["direct_only"]
    # Links shared before this change have a lowercase sort letter: any flights.
    assert parse_payload("g-SKG-europe-30-b-0-6-1500-10")[1]["direct_only"] is False


async def test_shared_direct_digest_is_added_as_direct(bot):
    payload = share_payload(digest(region="europe", direct_only=True, departure_date=future(20),
                                   departure_date_end=future(40)))
    await bot.send(f"/start {payload}")
    assert "Direct flights only" in bot.telegram.last_text
    await bot.press(bot.telegram.button_data("Add This Digest"))
    [added] = await bot.services.db.list_digests(USER_ID)
    assert added.direct_only


async def test_digests_from_before_get_any_flights(tmp_path):
    path = str(tmp_path / "farebot.db")
    db = Database(path)
    await db.migrate()
    created = await db.create_digest(USER_ID, "ATH", "europe", days_ahead=30)
    conn = sqlite3.connect(path)  # a schema v3 database had no direct_only column
    conn.execute("ALTER TABLE digests DROP COLUMN direct_only")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()

    await db.migrate()
    assert (await db.get_digest(created.id)).direct_only is False
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()
