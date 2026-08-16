import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.handlers.explore import start_explore_wizard as explore_command, select_explore_region_callback as explore_region_callback, track_deal_callback
from bot.handlers.digest import start_digest_wizard as digest_command
from bot.handlers.dashboard import mytracks_command, dashboard_callback_handler
from bot.handlers.track import start_newtrack, handle_origin_input, ORIGIN
from services.explore_engine import run_explore_query

# -------------------------------------------------------------------
# 1. Test /explore interactive region quick-selector keyboard
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_explore_command_no_args_shows_region_keyboard():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []  # No args passed to /explore

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        await explore_command(update, context)

    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    assert "Explore Top Flight Deals Wizard" in args[0]
    assert "reply_markup" in kwargs
    keyboard = kwargs["reply_markup"].inline_keyboard
    button_datas = [btn.callback_data for row in keyboard for btn in row]
    assert "expl_org_ATH_Athens" in button_datas
    assert "expl_org_SKG_Thessaloniki" in button_datas


# -------------------------------------------------------------------
# 2. Test explore_region_callback execution
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_explore_region_callback_renders_deals():
    update = MagicMock()
    update.effective_user.id = 123
    update.callback_query.data = "expl_reg_europe"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.edit_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        await explore_region_callback(update, context)

    update.callback_query.message.edit_text.assert_called()
    last_call_text = update.callback_query.message.edit_text.call_args[0][0]
    assert "Region set to: **EUROPE**" in last_call_text


# -------------------------------------------------------------------
# 3. Test explore engine destination deduplication
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_explore_engine_deduplicates_destinations():
    with patch("services.explore_engine.FastFlightsProvider") as provider_cls:
        provider = AsyncMock()

        def mock_search(origin, dst, date, currency="EUR"):
            if dst == "CDG":  # Return 2 offers for CDG
                return [
                    AsyncMock(price=192.0, airline="Air France", typical_min=250.0, typical_max=300.0, country="France"),
                    AsyncMock(price=192.0, airline="SKY Express", typical_min=250.0, typical_max=300.0, country="France")
                ]
            elif dst == "FCO":
                return [AsyncMock(price=120.0, airline="ITA Airways", typical_min=180.0, typical_max=220.0, country="Italy")]
            return []

        provider.search_flights.side_effect = mock_search
        provider_cls.return_value = provider

        deals = await run_explore_query("ATH", "europe", "2026-09-15")
        cdg_deals = [d for d in deals if d["destination_code"] == "CDG"]
        assert len(cdg_deals) == 1  # Only 1 unique CDG deal returned!


# -------------------------------------------------------------------
# 4. Test 1-tap deal tracking feedback (Telegram chat reply_text)
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_track_deal_callback_sends_chat_confirmation():
    update = MagicMock()
    update.callback_query.data = "track_deal_ATH_FCO_2026-09-15_120.0"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    update.effective_user.id = 123
    context = MagicMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.explore.db_manager") as db_mock:
            db_mock.has_active_tracker = AsyncMock(return_value=False)
            db_mock.get_active_trackers_count = AsyncMock(return_value=1)
            db_mock.create_tracker = AsyncMock(return_value=42)

            await track_deal_callback(update, context)

            update.callback_query.message.reply_text.assert_called_once()
        reply_msg = update.callback_query.message.reply_text.call_args[0][0]
        assert "✅ **Deal Tracked!**" in reply_msg
        assert "Tracker #42" in reply_msg
        assert "ATH ✈️ FCO" in reply_msg
        assert "€108.00" in reply_msg  # €120 - 10% = €108 target budget


# -------------------------------------------------------------------
# 5. Test /digest creates tracker record and formats /mytracks
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_digest_creates_db_tracker_and_appears_in_mytracks():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.job_queue = MagicMock()
    context.args = ["ATH", "europe", "80"]

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.digest.db_manager") as db_mock:
            db_mock.has_active_digest = AsyncMock(return_value=False)
            db_mock.create_tracker = AsyncMock(return_value=101)

            await digest_command(update, context)

            db_mock.create_tracker.assert_called_once()
            kw = db_mock.create_tracker.call_args[1]
            assert kw["destination_code"] == "REGION:EUROPE"
            assert kw["max_budget"] == 80.0

    # Now verify mytracks_command formats the digest card cleanly
    update_mytracks = MagicMock()
    update_mytracks.effective_user.id = 123
    update_mytracks.message.reply_text = AsyncMock()

    digest_tracker_row = {
        "id": 101,
        "user_id": 123,
        "origin_code": "ATH",
        "destination_code": "REGION:EUROPE",
        "destination_name": "Europe Digest",
        "departure_date": "2026-09-15",
        "max_budget": 80.0,
        "status": "ACTIVE",
        "direct_only": 0
    }

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.dashboard.db_manager") as dash_db_mock:
            dash_db_mock.get_user_trackers = AsyncMock(return_value=[digest_tracker_row])
            await mytracks_command(update_mytracks, context)

            update_mytracks.message.reply_text.assert_called_once()
            card_text = update_mytracks.message.reply_text.call_args[0][0]
            assert "🗞️ **Weekly Digest #101**" in card_text
            assert "ATH ✈️ EUROPE" in card_text
            assert "Every Week (Sunday)" in card_text


# -------------------------------------------------------------------
# 6. Test digest pause and resume via dashboard callback
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_digest_dashboard_pause_and_resume():
    update_pause = MagicMock()
    update_pause.callback_query.data = "dash_pause_101"
    update_pause.callback_query.answer = AsyncMock()
    update_pause.callback_query.message.edit_text = AsyncMock()
    update_pause.effective_user.id = 123
    context = MagicMock()
    context.job_queue = MagicMock()

    digest_tracker_row = {
        "id": 101,
        "user_id": 123,
        "origin_code": "ATH",
        "destination_code": "REGION:EUROPE",
        "max_budget": 80.0,
        "status": "ACTIVE"
    }

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.dashboard.db_manager") as db_mock:
            db_mock.get_tracker_by_id = AsyncMock(return_value=digest_tracker_row)
            db_mock.update_tracker_status = AsyncMock()
            with patch("bot.handlers.dashboard.unschedule_tracker_job") as unsched_mock:
                await dashboard_callback_handler(update_pause, context)
                unsched_mock.assert_called_once_with(context.job_queue, 101)

    update_resume = MagicMock()
    update_resume.callback_query.data = "dash_resume_101"
    update_resume.callback_query.answer = AsyncMock()
    update_resume.callback_query.message.edit_text = AsyncMock()
    update_resume.effective_user.id = 123

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.dashboard.db_manager") as db_mock:
            db_mock.get_tracker_by_id = AsyncMock(return_value=digest_tracker_row)
            db_mock.update_tracker_status = AsyncMock()
            with patch("daemon.scheduler.schedule_digest_job") as sched_digest_mock:
                await dashboard_callback_handler(update_resume, context)
                sched_digest_mock.assert_called_once_with(context.job_queue, 101, 123, "ATH", "europe", 80.0, "Sunday@15:00")
