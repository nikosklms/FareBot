from bot import auth

INTRUDER = 77777


async def test_allowed_user_reaches_handlers(bot):
    await bot.send("/start")
    assert "Welcome to Fare Bot" in bot.telegram.last_text


async def test_unknown_user_is_blocked_and_asks_for_access(bot):
    await bot.send("/search ATH PAR", user_id=INTRUDER)

    sent = bot.telegram.calls_to("sendMessage")
    admin_alert, reply = sent
    assert admin_alert["chat_id"] == 123 and "Access request" in admin_alert["text"]
    assert "/search ATH PAR" in admin_alert["text"]
    assert reply["chat_id"] == INTRUDER and "Access requested" in reply["text"]


async def test_unauthorized_button_press_gets_alert(bot):
    await bot.press("dash:del:t:1", user_id=INTRUDER)
    answer = bot.telegram.calls_to("answerCallbackQuery")[-1]
    assert answer["text"] == "⛔ Access denied" and answer["show_alert"] is True


async def test_unauthorized_user_never_reaches_wizard(bot):
    await bot.send("/track", user_id=INTRUDER)
    assert INTRUDER not in bot.app.user_data or "track" not in bot.app.user_data[INTRUDER]


async def test_edited_messages_get_a_hint_instead_of_running_again(bot, provider):
    await bot.send("/search skg ber 2026-11-07[..2026-11-21][direct]", edited=True)
    assert bot.telegram.last_text == auth.EDITED
    assert not provider.queries

    await bot.send("/search")  # starting a wizard, then editing an answer
    await bot.send("ATH", edited=True)
    assert bot.telegram.last_text == auth.EDITED


async def test_edited_messages_from_outsiders_are_ignored(bot):
    await bot.send("/start", user_id=INTRUDER, edited=True)
    assert not bot.telegram.calls_to("sendMessage")


async def test_usage_shows_real_examples_without_brackets(bot):
    await bot.send("/search skg ber 2026-11-07[..2026-11-21][direct]")
    assert "[" not in bot.telegram.last_text
    assert "/search ATH LON 2026-09-01..2026-09-15 direct" in bot.telegram.last_text
