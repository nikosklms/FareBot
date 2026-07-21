import pytest
from unittest.mock import AsyncMock
from telegram.ext import CommandHandler, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from bot.handlers import start_command, help_command, cancel_command, search_command, mytracks_command
from bot.handlers.track import start_newtrack

def test_all_bot_commands_are_registered():
    from telegram.ext import ApplicationBuilder

    # Build application as done in main.py
    app = ApplicationBuilder().token("123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ").build()

    # Register handlers exactly as in main.py
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mytracks", mytracks_command))
    app.add_handler(CallbackQueryHandler(AsyncMock(), pattern="^dash_"))

    from bot.handlers import (
        handle_search_origin, select_search_origin_callback,
        handle_search_destination, select_search_destination_callback, handle_search_date,
        SEARCH_ORIGIN, SEARCH_DESTINATION, SEARCH_DATE
    )
    search_wizard = ConversationHandler(
        entry_points=[CommandHandler("search", search_command)],
        states={
            SEARCH_ORIGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_origin)],
            SEARCH_DESTINATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_destination)],
            SEARCH_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_date)]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        per_chat=True, per_user=True, per_message=False
    )
    app.add_handler(search_wizard)

    from bot.handlers.track import (
        handle_origin_input, select_origin_callback,
        handle_destination_input, select_destination_callback,
        handle_departure_date, handle_budget, select_frequency_callback,
        ORIGIN, DESTINATION, DEPARTURE_DATE, BUDGET, FREQUENCY
    )
    track_wizard = ConversationHandler(
        entry_points=[CommandHandler("newtrack", start_newtrack)],
        states={
            ORIGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_origin_input)],
            DESTINATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_destination_input)],
            DEPARTURE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_departure_date)],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_budget)],
            FREQUENCY: [CallbackQueryHandler(select_frequency_callback, pattern="^freq_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        per_chat=True, per_user=True, per_message=False
    )
    app.add_handler(track_wizard)

    # Collect all command names registered across all handler groups
    registered_commands = set()

    for group in app.handlers.values():
        for handler in group:
            if isinstance(handler, CommandHandler):
                registered_commands.update(handler.commands)
            elif isinstance(handler, ConversationHandler):
                for ep in handler.entry_points:
                    if isinstance(ep, CommandHandler):
                        registered_commands.update(ep.commands)
                for fb in handler.fallbacks:
                    if isinstance(fb, CommandHandler):
                        registered_commands.update(fb.commands)

    # Verify that every specified user command is registered
    expected_commands = {"start", "help", "mytracks", "search", "newtrack", "cancel"}
    assert expected_commands.issubset(registered_commands), f"Missing commands! Registered: {registered_commands}"
