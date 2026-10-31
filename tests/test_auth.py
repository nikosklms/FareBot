import json

import aiosqlite

from bot import auth

INTRUDER = 77777


async def test_allowed_user_reaches_handlers(bot):
    await bot.send("/start")
    assert "Welcome to Fare Bot" in bot.telegram.last_text


async def test_unknown_user_is_blocked_logged_and_asks_for_access(bot):
    await bot.send("/search ATH PAR", user_id=INTRUDER)

    sent = bot.telegram.calls_to("sendMessage")
    admin_alert, reply = sent
    assert admin_alert["chat_id"] == 123 and "Access request" in admin_alert["text"]
    assert "/search ATH PAR" in admin_alert["text"]
    assert reply["chat_id"] == INTRUDER and "Access requested" in reply["text"]

    entry = json.loads(auth.UNAUTHORIZED_LOG.read_text())
    assert entry["user_id"] == INTRUDER and entry["input"] == "/search ATH PAR"
    async with aiosqlite.connect(bot.services.db.path) as conn:
        async with conn.execute("SELECT user_id, input_text FROM unauthorized_attempts") as cur:
            assert await cur.fetchall() == [(INTRUDER, "/search ATH PAR")]


async def test_unauthorized_button_press_gets_alert(bot):
    await bot.press("dash:del:t:1", user_id=INTRUDER)
    answer = bot.telegram.calls_to("answerCallbackQuery")[-1]
    assert answer["text"] == "⛔ Access denied" and answer["show_alert"] is True


async def test_unauthorized_user_never_reaches_wizard(bot):
    await bot.send("/track", user_id=INTRUDER)
    assert INTRUDER not in bot.app.user_data or "track" not in bot.app.user_data[INTRUDER]
