import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.handlers.common import start_command, help_command, cancel_command

@pytest.mark.asyncio
async def test_start_command():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await start_command(update, context)
    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    text = args[0] if args else kwargs.get("text", "")
    assert "Fare Bot" in text

@pytest.mark.asyncio
async def test_help_command():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await help_command(update, context)
    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    text = args[0] if args else kwargs.get("text", "")
    assert "Guide" in text or "Instant Search" in text

@pytest.mark.asyncio
async def test_cancel_command():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    res = await cancel_command(update, context)
    assert res == -1  # ConversationHandler.END is -1
    update.message.reply_text.assert_called_once()

def test_build_status_estimate_text_local_time():
    from bot.handlers.common import build_status_estimate_text
    from datetime import datetime, timedelta
    now_local = datetime.now().astimezone()
    completion_clock = (now_local + timedelta(seconds=180)).strftime("%H:%M")

    res = build_status_estimate_text("Test Header", est_seconds=180.0, total_queries=10, num_airports=2, num_days=5)
    assert f"around **{completion_clock}**" in res

@pytest.mark.asyncio
async def test_cancel_callback_cancels_active_task():
    from bot.handlers.common import cancel_callback
    task_mock = MagicMock()
    context = MagicMock()
    context.user_data = {"active_explore_task": task_mock}
    update = MagicMock()
    update.callback_query.message.edit_text = AsyncMock()
    update.callback_query.answer = AsyncMock()

    await cancel_callback(update, context)
    task_mock.cancel.assert_called_once()
    assert "active_explore_task" not in context.user_data


