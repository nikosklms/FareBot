import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.ext import ConversationHandler
from bot.handlers.track import (
    start_newtrack, handle_origin_input, select_origin_callback,
    handle_destination_input, select_destination_callback,
    handle_departure_date, select_flight_type_callback,
    handle_budget, select_frequency_callback,
    ORIGIN, DESTINATION, DEPARTURE_DATE, FLIGHT_TYPE, BUDGET, FREQUENCY
)


# ─── start_newtrack ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_newtrack_under_limit():
    """New tracker creation should proceed when user is under tracker limit."""
    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"stale_key": "should_be_cleared"}

    with patch("bot.handlers.track.db_manager") as db_mock:
        db_mock.get_active_trackers_count = AsyncMock(return_value=0)
        state = await start_newtrack(update, context)

    assert state == ORIGIN
    assert "stale_key" not in context.user_data  # user_data should be cleared
    msg = update.message.reply_text.call_args[0][0]
    assert "Step 1/6" in msg
    assert "flying from" in msg


@pytest.mark.asyncio
async def test_start_newtrack_one_line_command():
    """One-line /track command should parse all arguments and create tracker immediately."""
    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["ATH", "LON", "2028-09-01..2028-09-15", "150"]
    context.job_queue = MagicMock()

    with patch("bot.handlers.track.db_manager") as db_mock, \
         patch("bot.handlers.track.schedule_tracker_job") as sched_mock:
        db_mock.get_active_trackers_count = AsyncMock(return_value=0)
        db_mock.create_tracker = AsyncMock(return_value=99)

        state = await start_newtrack(update, context)

    assert state == ConversationHandler.END
    db_mock.create_tracker.assert_called_once_with(
        user_id=42,
        origin_code="ATH",
        origin_name="ATH",
        destination_code="LON",
        destination_name="LON",
        departure_date="2028-09-01",
        departure_date_end="2028-09-15",
        max_budget=150.0,
        frequency_hours=6,
        direct_only=0
    )
    sched_mock.assert_called_once_with(context.job_queue, 99, 6)


@pytest.mark.asyncio
async def test_start_newtrack_at_limit():
    """New tracker creation should be rejected when user already has MAX_TRACKERS_PER_USER."""
    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    with patch("bot.handlers.track.db_manager") as db_mock:
        db_mock.get_active_trackers_count = AsyncMock(return_value=5)  # MAX_TRACKERS_PER_USER = 5
        state = await start_newtrack(update, context)

    assert state == ConversationHandler.END
    msg = update.message.reply_text.call_args[0][0]
    assert "limit" in msg.lower()


# ─── handle_origin_input ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_origin_garbage_still_matches():
    """Resolver's fuzzy matching means even garbage input gets matches — user sees buttons, not errors."""
    update = MagicMock()
    update.message.text = "xyzgarbage999"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_origin_input(update, context)
    assert state == ORIGIN  # waiting for callback
    _, kwargs = update.message.reply_text.call_args
    # Fuzzy match still shows airport buttons
    assert kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_handle_origin_no_matches_shows_error():
    """If resolver returns empty (mocked), user sees 'not recognized' error."""
    update = MagicMock()
    update.message.text = "test"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    with patch("bot.handlers.track.resolver") as mock_resolver:
        mock_resolver.resolve.return_value = []
        state = await handle_origin_input(update, context)

    assert state == ORIGIN
    msg = update.message.reply_text.call_args[0][0]
    assert "not recognized" in msg.lower()


@pytest.mark.asyncio
async def test_handle_origin_valid_city_shows_buttons():
    """Valid origin city should present confirmation buttons."""
    update = MagicMock()
    update.message.text = "London"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_origin_input(update, context)
    assert state == ORIGIN  # stays until callback confirms
    _, kwargs = update.message.reply_text.call_args
    markup = kwargs.get("reply_markup")
    assert markup is not None
    # Should have airport buttons + "Search Again"
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any("Search Again" in btn.text for btn in buttons)
    assert any("sel_org_" in btn.callback_data for btn in buttons)


# ─── select_origin_callback ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_select_origin_callback_sets_origin():
    """Selecting an origin from buttons should store origin code and advance to DESTINATION."""
    update = MagicMock()
    query = MagicMock()
    query.data = "sel_org_ATH_Athens International"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    state = await select_origin_callback(update, context)
    assert state == DESTINATION
    assert context.user_data["origin_code"] == "ATH"
    assert context.user_data["origin_name"] == "Athens International"
    msg = query.message.edit_text.call_args[0][0]
    assert "ATH" in msg
    assert "Step 2/6" in msg


@pytest.mark.asyncio
async def test_select_origin_callback_search_again():
    """Pressing 'Search Again' on origin should stay in ORIGIN state."""
    update = MagicMock()
    query = MagicMock()
    query.data = "re_org"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    state = await select_origin_callback(update, context)
    assert state == ORIGIN


# ─── handle_destination_input ────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_destination_garbage_still_matches():
    """Resolver's fuzzy matching means even garbage destination gets matches."""
    update = MagicMock()
    update.message.text = "xyzgarbage999"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_destination_input(update, context)
    assert state == DESTINATION
    _, kwargs = update.message.reply_text.call_args
    assert kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_handle_destination_no_matches_shows_error():
    """If resolver returns empty (mocked), user sees 'not recognized' error."""
    update = MagicMock()
    update.message.text = "test"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    with patch("bot.handlers.track.resolver") as mock_resolver:
        mock_resolver.resolve.return_value = []
        state = await handle_destination_input(update, context)

    assert state == DESTINATION
    msg = update.message.reply_text.call_args[0][0]
    assert "not recognized" in msg.lower()


@pytest.mark.asyncio
async def test_handle_destination_valid_city_shows_buttons():
    """Valid destination city should present confirmation buttons."""
    update = MagicMock()
    update.message.text = "Budapest"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_destination_input(update, context)
    assert state == DESTINATION
    _, kwargs = update.message.reply_text.call_args
    markup = kwargs.get("reply_markup")
    assert markup is not None
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any("sel_dst_" in btn.callback_data for btn in buttons)
    assert any("BUD" in btn.text for btn in buttons)


# ─── select_destination_callback ─────────────────────────────────────

@pytest.mark.asyncio
async def test_select_destination_callback_sets_destination():
    """Selecting a destination should store code and advance to DEPARTURE_DATE."""
    update = MagicMock()
    query = MagicMock()
    query.data = "sel_dst_BUD_Budapest"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    state = await select_destination_callback(update, context)
    assert state == DEPARTURE_DATE
    assert context.user_data["destination_code"] == "BUD"
    assert context.user_data["destination_name"] == "Budapest"
    msg = query.message.edit_text.call_args[0][0]
    assert "BUD" in msg
    assert "Step 3/6" in msg


@pytest.mark.asyncio
async def test_select_destination_callback_search_again():
    """Pressing 'Search Again' on destination should stay in DESTINATION state."""
    update = MagicMock()
    query = MagicMock()
    query.data = "re_dst"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    state = await select_destination_callback(update, context)
    assert state == DESTINATION


# ─── handle_departure_date ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_departure_date_invalid_format():
    """Non-date input should stay in DEPARTURE_DATE."""
    update = MagicMock()
    update.message.text = "next-tuesday"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_departure_date(update, context)
    assert state == DEPARTURE_DATE
    assert "Invalid date" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_departure_date_past_date():
    """Past date should stay in DEPARTURE_DATE."""
    update = MagicMock()
    update.message.text = "2020-06-15"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_departure_date(update, context)
    assert state == DEPARTURE_DATE
    assert "past" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_handle_departure_date_valid_shows_flight_type_buttons():
    """Valid future date should store date and show Direct/Any flight type buttons."""
    update = MagicMock()
    update.message.text = "2028-03-15"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_departure_date(update, context)
    assert state == FLIGHT_TYPE
    assert context.user_data["departure_date"] == "2028-03-15"
    _, kwargs = update.message.reply_text.call_args
    markup = kwargs.get("reply_markup")
    assert markup is not None
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any("Direct" in btn.text for btn in buttons)
    assert any("Any" in btn.text for btn in buttons)
    assert any("fl_type_1" in btn.callback_data for btn in buttons)
    assert any("fl_type_0" in btn.callback_data for btn in buttons)


@pytest.mark.asyncio
async def test_handle_departure_date_range():
    """Date range input should store start and end dates and advance to FLIGHT_TYPE."""
    from bot.handlers.track import handle_departure_date, FLIGHT_TYPE
    update = MagicMock()
    update.message.text = "2028-03-15..2028-03-25"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_departure_date(update, context)
    assert state == FLIGHT_TYPE
    assert context.user_data["departure_date"] == "2028-03-15"
    assert context.user_data["departure_date_end"] == "2028-03-25"


@pytest.mark.asyncio
async def test_handle_date_preset_callback():
    """Preset button callback should store calculated start and end dates."""
    from bot.handlers.track import handle_date_preset_callback, FLIGHT_TYPE
    update = MagicMock()
    query = MagicMock()
    query.data = "datepreset_next_7_days"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    state = await handle_date_preset_callback(update, context)
    assert state == FLIGHT_TYPE
    assert context.user_data.get("departure_date") is not None
    assert context.user_data.get("departure_date_end") is not None


# ─── select_flight_type_callback ─────────────────────────────────────

@pytest.mark.asyncio
async def test_select_flight_type_direct():
    """Selecting 'Direct' should set direct_only=1 and advance to BUDGET."""
    update = MagicMock()
    query = MagicMock()
    query.data = "fl_type_1"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    state = await select_flight_type_callback(update, context)
    assert state == BUDGET
    assert context.user_data["direct_only"] == 1
    msg = query.message.edit_text.call_args[0][0]
    assert "Direct" in msg
    assert "Step 5/6" in msg


@pytest.mark.asyncio
async def test_select_flight_type_any():
    """Selecting 'Any' should set direct_only=0 and advance to BUDGET."""
    update = MagicMock()
    query = MagicMock()
    query.data = "fl_type_0"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    state = await select_flight_type_callback(update, context)
    assert state == BUDGET
    assert context.user_data["direct_only"] == 0
    msg = query.message.edit_text.call_args[0][0]
    assert "Any" in msg


# ─── handle_budget ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_budget_negative():
    """Negative budget should stay in BUDGET."""
    update = MagicMock()
    update.message.text = "-100"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_budget(update, context)
    assert state == BUDGET


@pytest.mark.asyncio
async def test_handle_budget_zero():
    """Zero budget should stay in BUDGET."""
    update = MagicMock()
    update.message.text = "0"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_budget(update, context)
    assert state == BUDGET


@pytest.mark.asyncio
async def test_handle_budget_non_numeric():
    """Non-numeric budget should stay in BUDGET."""
    update = MagicMock()
    update.message.text = "cheap please"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_budget(update, context)
    assert state == BUDGET
    assert "Invalid" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_budget_valid_shows_frequency_buttons():
    """Valid positive budget should store it and show frequency options."""
    update = MagicMock()
    update.message.text = "250"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_budget(update, context)
    assert state == FREQUENCY
    assert context.user_data["max_budget"] == 250.0
    _, kwargs = update.message.reply_text.call_args
    markup = kwargs.get("reply_markup")
    assert markup is not None
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert any("freq_6" in btn.callback_data for btn in buttons)
    assert any("freq_12" in btn.callback_data for btn in buttons)
    assert any("freq_24" in btn.callback_data for btn in buttons)


@pytest.mark.asyncio
async def test_handle_budget_decimal():
    """Decimal budget like '99.99' should be accepted."""
    update = MagicMock()
    update.message.text = "99.99"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    state = await handle_budget(update, context)
    assert state == FREQUENCY
    assert context.user_data["max_budget"] == 99.99


# ─── select_frequency_callback (final step — creates tracker) ────────

@pytest.mark.asyncio
async def test_select_frequency_creates_tracker_and_schedules_job():
    """Final frequency selection should create a DB tracker, schedule a job, and show confirmation."""
    update = MagicMock()
    query = MagicMock()
    query.data = "freq_12"
    query.from_user.id = 42
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query

    context = MagicMock()
    context.user_data = {
        "origin_code": "ATH",
        "origin_name": "Athens International",
        "destination_code": "BUD",
        "destination_name": "Budapest",
        "departure_date": "2028-03-15",
        "max_budget": 250.0,
        "direct_only": 1
    }
    context.job_queue = MagicMock()

    with patch("bot.handlers.track.db_manager") as db_mock, \
         patch("bot.handlers.track.schedule_tracker_job") as sched_mock:
        db_mock.create_tracker = AsyncMock(return_value=77)
        state = await select_frequency_callback(update, context)

    assert state == ConversationHandler.END

    # Verify tracker was created with correct params
    db_mock.create_tracker.assert_called_once_with(
        user_id=42,
        origin_code="ATH",
        origin_name="Athens International",
        destination_code="BUD",
        destination_name="Budapest",
        departure_date="2028-03-15",
        departure_date_end=None,
        max_budget=250.0,
        frequency_hours=12,
        direct_only=1
    )

    # Verify job was scheduled
    sched_mock.assert_called_once_with(context.job_queue, 77, 12)

    # Verify confirmation message
    msg = query.message.edit_text.call_args[0][0]
    assert "ATH" in msg and "BUD" in msg
    assert "2028-03-15" in msg
    assert "250.00" in msg
    assert "12 hours" in msg
    assert "Direct" in msg


@pytest.mark.asyncio
async def test_select_frequency_with_any_flight_type():
    """Final step with direct_only=0 should show 'Any Flights' in confirmation."""
    update = MagicMock()
    query = MagicMock()
    query.data = "freq_6"
    query.from_user.id = 99
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query

    context = MagicMock()
    context.user_data = {
        "origin_code": "SKG",
        "origin_name": "Thessaloniki",
        "destination_code": "LON",
        "destination_name": "London",
        "departure_date": "2028-06-01",
        "max_budget": 100.0,
        "direct_only": 0
    }
    context.job_queue = MagicMock()

    with patch("bot.handlers.track.db_manager") as db_mock, \
         patch("bot.handlers.track.schedule_tracker_job") as sched_mock:
        db_mock.create_tracker = AsyncMock(return_value=88)
        state = await select_frequency_callback(update, context)

    assert state == ConversationHandler.END
    msg = query.message.edit_text.call_args[0][0]
    assert "Any Flights" in msg
    assert "6 hours" in msg


@pytest.mark.asyncio
async def test_select_frequency_no_job_queue():
    """If job_queue is None (missing), tracker should still be created but no job scheduled."""
    update = MagicMock()
    query = MagicMock()
    query.data = "freq_24"
    query.from_user.id = 55
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query

    context = MagicMock()
    context.user_data = {
        "origin_code": "ATH",
        "origin_name": "Athens",
        "destination_code": "PAR",
        "destination_name": "Paris",
        "departure_date": "2028-01-01",
        "max_budget": 300.0,
        "direct_only": 0
    }
    context.job_queue = None  # No job queue

    with patch("bot.handlers.track.db_manager") as db_mock, \
         patch("bot.handlers.track.schedule_tracker_job") as sched_mock:
        db_mock.create_tracker = AsyncMock(return_value=99)
        state = await select_frequency_callback(update, context)

    assert state == ConversationHandler.END
    db_mock.create_tracker.assert_called_once()
    sched_mock.assert_not_called()  # No crash, just skipped


# ─── Full wizard flow simulation ─────────────────────────────────────

@pytest.mark.asyncio
async def test_full_wizard_flow_end_to_end():
    """Simulate the entire 6-step /newtrack wizard end-to-end."""
    context = MagicMock()
    context.user_data = {}
    context.job_queue = MagicMock()

    # Step 1: start_newtrack
    update1 = MagicMock()
    update1.effective_user.id = 42
    update1.message.reply_text = AsyncMock()
    with patch("bot.handlers.track.db_manager") as db_mock:
        db_mock.get_active_trackers_count = AsyncMock(return_value=0)
        s1 = await start_newtrack(update1, context)
    assert s1 == ORIGIN

    # Step 2: handle_origin_input — user types "Athens"
    update2 = MagicMock()
    update2.message.text = "Athens"
    update2.message.reply_text = AsyncMock()
    s2 = await handle_origin_input(update2, context)
    assert s2 == ORIGIN  # waiting for callback

    # Step 3: select_origin_callback — user picks ATH
    update3 = MagicMock()
    query3 = MagicMock()
    query3.data = "sel_org_ATH_Athens International"
    query3.answer = AsyncMock()
    query3.message.edit_text = AsyncMock()
    update3.callback_query = query3
    s3 = await select_origin_callback(update3, context)
    assert s3 == DESTINATION
    assert context.user_data["origin_code"] == "ATH"

    # Step 4: handle_destination_input — user types "Budapest"
    update4 = MagicMock()
    update4.message.text = "Budapest"
    update4.message.reply_text = AsyncMock()
    s4 = await handle_destination_input(update4, context)
    assert s4 == DESTINATION  # waiting for callback

    # Step 5: select_destination_callback — user picks BUD
    update5 = MagicMock()
    query5 = MagicMock()
    query5.data = "sel_dst_BUD_Budapest"
    query5.answer = AsyncMock()
    query5.message.edit_text = AsyncMock()
    update5.callback_query = query5
    s5 = await select_destination_callback(update5, context)
    assert s5 == DEPARTURE_DATE
    assert context.user_data["destination_code"] == "BUD"

    # Step 6: handle_departure_date — user types valid date
    update6 = MagicMock()
    update6.message.text = "2028-09-20"
    update6.message.reply_text = AsyncMock()
    s6 = await handle_departure_date(update6, context)
    assert s6 == FLIGHT_TYPE
    assert context.user_data["departure_date"] == "2028-09-20"

    # Step 7: select_flight_type_callback — user picks "Direct"
    update7 = MagicMock()
    query7 = MagicMock()
    query7.data = "fl_type_1"
    query7.answer = AsyncMock()
    query7.message.edit_text = AsyncMock()
    update7.callback_query = query7
    s7 = await select_flight_type_callback(update7, context)
    assert s7 == BUDGET
    assert context.user_data["direct_only"] == 1

    # Step 8: handle_budget — user types "200"
    update8 = MagicMock()
    update8.message.text = "200"
    update8.message.reply_text = AsyncMock()
    s8 = await handle_budget(update8, context)
    assert s8 == FREQUENCY
    assert context.user_data["max_budget"] == 200.0

    # Step 9: select_frequency_callback — user picks every 6 hours
    update9 = MagicMock()
    query9 = MagicMock()
    query9.data = "freq_6"
    query9.from_user.id = 42
    query9.answer = AsyncMock()
    query9.message.edit_text = AsyncMock()
    update9.callback_query = query9

    with patch("bot.handlers.track.db_manager") as db_mock, \
         patch("bot.handlers.track.schedule_tracker_job") as sched_mock:
        db_mock.create_tracker = AsyncMock(return_value=1)
        s9 = await select_frequency_callback(update9, context)

    assert s9 == ConversationHandler.END
    db_mock.create_tracker.assert_called_once_with(
        user_id=42,
        origin_code="ATH",
        origin_name="Athens International",
        destination_code="BUD",
        destination_name="Budapest",
        departure_date="2028-09-20",
        departure_date_end=None,
        max_budget=200.0,
        frequency_hours=6,
        direct_only=1
    )
    sched_mock.assert_called_once_with(context.job_queue, 1, 6)

    # Confirmation message should include all details
    msg = query9.message.edit_text.call_args[0][0]
    assert "ATH" in msg
    assert "BUD" in msg
    assert "2028-09-20" in msg
    assert "200.00" in msg
    assert "Direct" in msg
    assert "6 hours" in msg
