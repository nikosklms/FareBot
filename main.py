import logging
import warnings
from telegram.warnings import PTBUserWarning

# Suppress PTBUserWarning for CallbackQueryHandler in ConversationHandler
warnings.filterwarnings("ignore", category=PTBUserWarning)

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from config import TELEGRAM_BOT_TOKEN, check_config
from database.db import init_db
from bot.handlers import (
    start_command,
    help_command,
    cancel_command,
    start_newtrack,
    handle_origin_input,
    select_origin_callback,
    handle_destination_input,
    select_destination_callback,
    handle_departure_date,
    handle_date_preset_callback,
    select_flight_type_callback,
    handle_budget,
    select_frequency_callback,
    mytracks_command,
    dashboard_callback_handler,
    search_command,
    handle_search_origin,
    select_search_origin_callback,
    handle_search_destination,
    select_search_destination_callback,
    handle_search_date,
    select_search_flight_type_callback,
    search_track_callback_handler,
    ORIGIN,
    DESTINATION,
    DEPARTURE_DATE,
    FLIGHT_TYPE,
    BUDGET,
    FREQUENCY,
    SEARCH_ORIGIN,
    SEARCH_DESTINATION,
    SEARCH_DATE,
    SEARCH_FLIGHT_TYPE
)
from daemon import register_active_trackers

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(application):
    """Register bot commands menu in Telegram UI and initialize active background trackers."""
    try:
        commands = [
            ("search", "🔍 Search instant flight offers"),
            ("track", "🔔 Track flight prices"),
            ("newtrack", "🔔 Track flight prices (wizard)"),
            ("mytracks", "📊 Manage price trackers"),
            ("help", "❓ Show help menu"),
            ("start", "🚀 Start bot menu"),
            ("cancel", "❌ Cancel active search/wizard")
        ]
        await application.bot.set_my_commands(commands)
        logger.info("Successfully registered Telegram Bot Commands Menu.")

        register_active_trackers(application)
    except Exception as e:
        logging.warning(f"Failed to set Telegram Bot Commands Menu: {e}")

def main():
    check_config()
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mytracks", mytracks_command))
    app.add_handler(CallbackQueryHandler(dashboard_callback_handler, pattern="^dash_"))
    app.add_handler(CallbackQueryHandler(search_track_callback_handler, pattern="^track_"))

    # Register search wizard
    search_wizard = ConversationHandler(
        entry_points=[CommandHandler("search", search_command)],
        states={
            SEARCH_ORIGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_origin),
                CallbackQueryHandler(select_search_origin_callback, pattern="^src_org_|re_src_org")
            ],
            SEARCH_DESTINATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_destination),
                CallbackQueryHandler(select_search_destination_callback, pattern="^src_dst_|re_src_dst")
            ],
            SEARCH_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_date)],
            SEARCH_FLIGHT_TYPE: [CallbackQueryHandler(select_search_flight_type_callback, pattern="^src_fl_type_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        per_chat=True,
        per_user=True
    )
    app.add_handler(search_wizard)

    # Register track wizard
    track_wizard = ConversationHandler(
        entry_points=[CommandHandler("newtrack", start_newtrack), CommandHandler("track", start_newtrack)],
        states={
            ORIGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_origin_input),
                CallbackQueryHandler(select_origin_callback, pattern="^sel_org_|re_org")
            ],
            DESTINATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_destination_input),
                CallbackQueryHandler(select_destination_callback, pattern="^sel_dst_|re_dst")
            ],
            DEPARTURE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_departure_date),
                CallbackQueryHandler(handle_date_preset_callback, pattern="^datepreset_")
            ],
            FLIGHT_TYPE: [CallbackQueryHandler(select_flight_type_callback, pattern="^fl_type_")],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_budget)],
            FREQUENCY: [CallbackQueryHandler(select_frequency_callback, pattern="^freq_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        per_chat=True,
        per_user=True
    )
    app.add_handler(track_wizard)


    print("🤖 Fare Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
