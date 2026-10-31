from datetime import timedelta

from bot.handlers.access import ADMIN_ONLY
from bot.handlers.stats import stats_text
from database.models import APPROVED
from providers.base import ProviderStats
from tests.fakes import USER_ID, future

MARIA = 555


async def test_admin_sees_searches_cache_and_users(bot, provider):
    provider.stats = lambda: ProviderStats(searches=200, from_cache=80, shared=20, google_requests=110,
                                           rate_limit_pauses=1, paused_for=45, average_latency=0.42)
    db = bot.services.db
    await db.create_tracker(user_id=USER_ID, origin_code="ATH", destination_code="LON",
                            departure_date=future(10), max_budget=80.0)
    await db.create_digest(USER_ID, "SKG", "europe", days_ahead=30)
    await db.request_access(MARIA, "@maria", "Maria")
    await db.set_user_status(MARIA, APPROVED)
    await db.request_access(777, None, "Someone")

    await bot.send("/stats")

    text = bot.telegram.last_text
    assert "🔍 <b>Searches</b>: 200" in text
    assert "Answered from the cache: 80 (40%)" in text and "Joined a search already running: 20 (10%)" in text
    assert "Saved in total: 100 (50%)" in text
    assert "Google requests</b>: 110, 0.42s each" in text
    assert "Rate-limit pauses</b>: 1 · paused now, 45s left" in text
    assert "1 always allowed · 1 approved · 1 waiting" in text
    assert "1 tracker · 1 digest" in text


async def test_stats_before_any_search(bot):
    text = await stats_text(bot.services, bot.services.started_at + timedelta(hours=2, minutes=5))
    assert "(2h 5m)" in text
    assert "Searches</b>: 0" in text and "Google requests</b>: 0\n" in text and "not paused" in text


async def test_only_the_admin_can_see_stats(bot):
    db = bot.services.db
    await db.request_access(MARIA, "@maria", "Maria")
    await db.set_user_status(MARIA, APPROVED)
    await bot.send("/stats", user_id=MARIA)
    assert bot.telegram.last_text == ADMIN_ONLY
