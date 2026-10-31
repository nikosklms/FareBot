from bot import auth
from daemon.scheduler import check_tracker
from database.models import APPROVED, DENIED, PAUSED, PENDING
from tests.fakes import USER_ID, future

MARIA = 555
OTHER = 777


def sent_to(bot, chat_id):
    return [call["text"] for call in bot.telegram.calls_to("sendMessage") if call["chat_id"] == chat_id]


async def request(bot, user_id=MARIA):
    await bot.send("/start", user_id=user_id)


async def test_request_then_approve_lets_the_user_in(bot):
    await request(bot)
    assert "Access requested" in sent_to(bot, MARIA)[-1]
    assert ("✅ Approve", f"acc:ok:{MARIA}:r") in bot.telegram.last_buttons()
    assert (await bot.services.db.get_user(MARIA)).status == PENDING

    await bot.press(f"acc:ok:{MARIA}:r")
    edited = bot.telegram.calls_to("editMessageText")[-1]
    assert "✅ Approved" in edited["text"] and "reply_markup" not in edited
    assert "You're in" in sent_to(bot, MARIA)[-1]

    await bot.send("/start", user_id=MARIA)
    assert "Welcome to Fare Bot" in sent_to(bot, MARIA)[-1]


async def test_waiting_users_are_not_reported_twice(bot):
    await request(bot)
    alerts = len(sent_to(bot, USER_ID))
    await bot.send("/search", user_id=MARIA)
    assert "still waiting" in sent_to(bot, MARIA)[-1]
    assert len(sent_to(bot, USER_ID)) == alerts


async def test_denied_users_stay_out_quietly(bot):
    await request(bot)
    await bot.press(f"acc:no:{MARIA}:r")
    assert "❌ Denied" in bot.telegram.last_text
    assert "wasn't approved" in sent_to(bot, MARIA)[-1]
    calls = len(bot.telegram.calls)
    attempts = auth.UNAUTHORIZED_LOG.read_text()

    for _ in range(5):
        await bot.send("/start", user_id=MARIA)
    await bot.press("dash:del:t:1", user_id=MARIA)
    assert [endpoint for endpoint, _ in bot.telegram.calls[calls:]] == ["answerCallbackQuery"]
    assert auth.UNAUTHORIZED_LOG.read_text() == attempts


async def test_only_the_admin_can_decide(bot):
    await request(bot)
    await request(bot, OTHER)
    await bot.press(f"acc:ok:{OTHER}:r")
    await bot.press(f"acc:ok:{MARIA}:r", user_id=OTHER)  # OTHER is approved now, but not the admin
    answer = bot.telegram.calls_to("answerCallbackQuery")[-1]
    assert "Only the bot's admin" in answer["text"]
    assert (await bot.services.db.get_user(MARIA)).status == PENDING

    await bot.send("/users", user_id=OTHER)
    assert "Only the bot's admin" in sent_to(bot, OTHER)[-1]


async def test_users_list_approves_and_removes(bot):
    await request(bot)
    await bot.send("/users")
    assert "⏳ <b>Waiting</b> (1)" in bot.telegram.last_text and str(MARIA) in bot.telegram.last_text

    await bot.press(f"acc:ok:{MARIA}:l")
    assert "✅ <b>Approved</b> (1)" in bot.telegram.last_text
    assert ("🚫 Remove Test", f"acc:rm:{MARIA}:l") in bot.telegram.last_buttons()

    await bot.press(f"acc:rm:{MARIA}:l")
    assert await bot.services.db.get_user(MARIA) is None
    assert "access to this bot was removed" in sent_to(bot, MARIA)[-1]

    await request(bot)  # removed users can ask again
    assert "Access requested" in sent_to(bot, MARIA)[-1]


async def test_a_second_tap_on_an_old_request_changes_nothing(bot):
    await request(bot)
    await bot.press(f"acc:ok:{MARIA}:r")
    messages = len(sent_to(bot, MARIA))
    await bot.press(f"acc:ok:{MARIA}:r")
    assert len(sent_to(bot, MARIA)) == messages
    assert (await bot.services.db.get_user(MARIA)).status == APPROVED

    await bot.press(f"acc:no:{MARIA}:l")
    assert (await bot.services.db.get_user(MARIA)).status == DENIED


async def test_approved_users_trackers_run_and_removed_ones_pause(bot, provider):
    await request(bot)
    await bot.press(f"acc:ok:{MARIA}:r")
    tracker = await bot.services.db.create_tracker(MARIA, "ATH", "LON", future(10), 100.0)
    assert await check_tracker(bot.services, bot.app.bot, tracker.id) is True

    await bot.press(f"acc:rm:{MARIA}:l")
    assert await check_tracker(bot.services, bot.app.bot, tracker.id) is False
    assert (await bot.services.db.get_tracker(tracker.id)).status == PAUSED
