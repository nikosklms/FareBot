from telegram.ext import CommandHandler, ConversationHandler

from bot.handlers import BOT_COMMANDS


def registered_commands(app) -> set[str]:
    commands = set()
    for handlers in app.handlers.values():
        for handler in handlers:
            if isinstance(handler, CommandHandler):
                commands |= handler.commands
            elif isinstance(handler, ConversationHandler):
                for entry in handler.entry_points:
                    commands |= getattr(entry, "commands", set())
    return commands


async def test_every_menu_command_has_a_handler(bot):
    assert {name for name, _ in BOT_COMMANDS} | {"start"} <= registered_commands(bot.app)


async def test_start_and_help(bot):
    await bot.send("/start")
    assert "Welcome to Fare Bot" in bot.telegram.last_text
    await bot.send("/help")
    help_text = bot.telegram.last_text
    for command in ("/search", "/track", "/explore", "/digest", "/mytracks"):
        assert command in help_text


async def test_noop_buttons_are_answered(bot):
    await bot.press("noop")
    assert bot.telegram.calls[-1][0] == "answerCallbackQuery"


async def test_stop_with_nothing_running(bot):
    await bot.press("task:stop")
    assert bot.telegram.alerts[-1] == "Nothing is running."


async def test_unexpected_errors_are_reported_to_the_user(bot, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(bot.services.db, "list_trackers", broken)
    await bot.send("/mytracks")
    assert "Something went wrong" in bot.telegram.last_text
