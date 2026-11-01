"""Origin steps offer the airports the user recently flew from, not a fixed list."""
import sqlite3

from tests.fakes import USER_ID, future


def origin_buttons(bot, prefix: str) -> list[str]:
    return [data.rsplit(":", 1)[1] for _, data in bot.telegram.last_buttons() if data.startswith(prefix)]


async def test_a_new_user_gets_no_airport_buttons(bot):
    await bot.send("/explore")
    assert origin_buttons(bot, "exp:org:") == []
    assert "(e.g. Athens, ATH)" in bot.telegram.last_text


async def test_recent_searches_come_first_then_trackers_and_digests(bot):
    db = bot.services.db
    await db.create_tracker(USER_ID, "HER", "LON", future(10), 100.0)
    await db.create_digest(USER_ID, "VIE", "europe", days_ahead=30)
    conn = sqlite3.connect(db.path)
    conn.execute("UPDATE trackers SET created_at = '2026-01-01 10:00:00'")  # older than the digest
    conn.commit()
    conn.close()
    await bot.send(f"/search SKG LON {future(5)}")
    await bot.finish_background_task()

    for command, prefix in (("/explore", "exp:org:"), ("/digest", "dig:org:"), ("/search", "src:org:"),
                            ("/track", "trk:org:")):
        await bot.send(command)
        assert origin_buttons(bot, prefix) == ["SKG", "VIE", "HER"], command
    assert "SKG - Thessaloniki" in bot.telegram.last_buttons()[0][0]


async def test_at_most_4_and_each_once(bot):
    for origin in ("ATH", "SKG", "HER", "VIE", "ATH"):
        await bot.send(f"/explore {origin} europe 1")
        await bot.finish_background_task()
    await bot.send("/explore")
    assert origin_buttons(bot, "exp:org:") == ["ATH", "VIE", "HER", "SKG"]
    await bot.press("exp:org:VIE")
    assert "<b>From</b>: VIE" in bot.telegram.last_text
