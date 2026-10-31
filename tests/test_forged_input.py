"""Button data and typed text come from the user's Telegram app, so a modified app can send anything."""
import pytest

from database.models import APPROVED
from tests.fakes import USER_ID, future
from tests.test_search import start_to_dates

MARIA = 555
BROKEN = "This button doesn't work."


@pytest.mark.parametrize("data", [
    "trk:add:ATH:LON:2026-02-31::50.00:1",          # impossible date
    "trk:add:ATH:LON:not-a-date::50.00:1",
    f"trk:add:ATH:LON:{future(5)}::0.00:1",          # budget must be above 0
    f"trk:add:ATH:LON:{future(5)}::nan:1",
    f"trk:add:ATH:LON:{future(5)}::-5.00:1",
    f"trk:add:ath:<b>:{future(5)}::50.00:1",         # not airport codes
    f"trk:add:ATH:LON:{future(5)}::50.00:7",
    "trk:add:ATH:LON",
])
async def test_forged_track_buttons_are_refused(bot, data):
    await bot.press(data)
    assert bot.telegram.alerts[-1] == BROKEN
    assert await bot.services.db.count_active(USER_ID) == 0


async def test_track_buttons_for_past_dates_say_why(bot):
    await bot.press("trk:add:ATH:LON:2020-01-01::50.00:1")
    assert "in the past" in bot.telegram.alerts[-1]
    assert await bot.services.db.count_active(USER_ID) == 0


async def test_a_forged_track_button_cant_get_around_the_range_limit(bot):
    await bot.services.db.request_access(MARIA, "@maria", "Maria")
    await bot.services.db.set_user_status(MARIA, APPROVED)
    await bot.press(f"trk:add:ATH:LON:{future(1)}:{future(300)}:50.00:1", user_id=MARIA)
    assert "the most you can search is 180 days" in bot.telegram.alerts[-1]
    assert await bot.services.db.count_active(MARIA) == 0

    await bot.press(f"trk:add:ATH:LON:{future(1)}:{future(180)}:50.00:1", user_id=MARIA)
    assert await bot.services.db.count_active(MARIA) == 1


async def test_typed_html_is_shown_as_text(bot):
    await bot.send("/search <<<>>> ATH 2026-12-01")
    assert "I don't know '&lt;&lt;&lt;&gt;&gt;&gt;'" in bot.telegram.last_text


async def test_a_forged_calendar_month_is_ignored(bot):
    await start_to_dates(bot)
    await bot.press("src:date:cal:open")
    calls = len(bot.telegram.calls)
    await bot.press("src:date:cal:nav:2026-13")
    assert [endpoint for endpoint, _ in bot.telegram.calls[calls:]] == ["answerCallbackQuery"]
    await bot.press(f"src:date:cal:day:{future(12)}")  # the calendar still works
    assert "Now pick the last day" in bot.telegram.last_text
