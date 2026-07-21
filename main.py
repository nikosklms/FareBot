import logging
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, CallbackQueryHandler, filters
from config import TELEGRAM_BOT_TOKEN, DB_PATH
from database.db import DatabaseManager
from providers.fast_flights import FastFlightsProvider
from daemon.scheduler import TrackerDaemonScheduler
from bot.handlers import start_command, help_command, cancel_command, execute_search
from bot.handlers.track import (
    start_newtrack, handle_origin_input, select_origin_callback,
    handle_destination_input, select_destination_callback,
    handle_departure_date, handle_budget, select_frequency_callback,
    ORIGIN, DESTINATION, DEPARTURE_DATE, BUDGET, FREQUENCY
)
from bot.handlers.dashboard import mytracks_command, dashboard_callback_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

async def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable is not set!")
        return

    db = DatabaseManager(DB_PATH)
    await db.init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mytracks", mytracks_command))
    app.add_handler(CallbackQueryHandler(dashboard_callback_handler, pattern="^dash_"))

    track_wizard = ConversationHandler(
        entry_points=[CommandHandler("newtrack", start_newtrack)],
        states={
            ORIGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_origin_input),
                CallbackQueryHandler(select_origin_callback, pattern="^sel_org_|re_org")
            ],
            DESTINATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_destination_input),
                CallbackQueryHandler(select_destination_callback, pattern="^sel_dst_|re_dst")
            ],
            DEPARTURE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_departure_date)],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_budget)],
            FREQUENCY: [CallbackQueryHandler(select_frequency_callback, pattern="^freq_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)]
    )
    app.add_handler(track_wizard)

    print("🤖 Fare Bot is starting...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
