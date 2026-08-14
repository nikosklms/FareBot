import logging
import warnings
from telegram.warnings import PTBUserWarning

# Suppress PTBUserWarning for CallbackQueryHandler in ConversationHandler
from datetime import datetime, timezone
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
    cancel_callback,
    start_newtrack,
    handle_origin_input,
    select_origin_callback,
    handle_destination_input,
    select_destination_callback,
    handle_departure_date,
    select_flight_type_callback,
    handle_budget,
    select_frequency_callback,
    mytracks_command,
    dashboard_callback_handler,
    handle_edit_budget_input,
    start_explore_wizard,
    handle_explore_origin_input,
    select_explore_origin_callback,
    select_explore_region_callback,
    handle_explore_budget_input,
    select_explore_budget_callback,
    handle_explore_limit_input,
    select_explore_limit_callback,
    EXPLORE_ORIGIN,
    EXPLORE_REGION,
    EXPLORE_BUDGET,
    EXPLORE_LIMIT,
    digest_command,
    track_deal_callback,
    search_command,
    handle_search_origin,
    select_search_origin_callback,
    handle_search_destination,
    select_search_destination_callback,
    handle_search_date,
    handle_search_date_preset_callback,
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
from daemon import register_active_trackers, run_daily_cleanup_job

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def post_init(application):
    """Register bot commands menu in Telegram UI and initialize active background trackers."""
    try:
        commands = [
            ("search", "🔍 Search instant flight offers"),
            ("explore", "🌟 Discover top discount flight deals"),
            ("digest", "🗞️ Weekly flight deal digest"),
            ("newtrack", "🔔 Track flight prices"),
            ("mytracks", "📊 Manage price trackers"),
            ("help", "❓ Show help menu"),
            ("start", "🚀 Start bot menu"),
            ("cancel", "❌ Cancel active search/wizard")
        ]
        await application.bot.set_my_commands(commands)
        logger.info("Successfully registered Telegram Bot Commands Menu.")

        register_active_trackers(application)

        if application.job_queue:
            application.job_queue.run_daily(
                run_daily_cleanup_job,
                time=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).time(),
                name="daily_cleanup_daemon"
            )
    except Exception as e:
        logging.warning(f"Failed to set Telegram Bot Commands Menu: {e}")

import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Silence HTTP server logs

def start_health_check_server():
    port = int(os.getenv("PORT", "10000"))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Started HTTP health check server on port {port}")
    except Exception as e:
        logger.warning(f"Could not start health check server: {e}")

def main():
    check_config()
    init_db()
    start_health_check_server()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("digest", digest_command))
    app.add_handler(CommandHandler("mytracks", mytracks_command))
    app.add_handler(CallbackQueryHandler(dashboard_callback_handler, pattern="^dash_"))
    app.add_handler(CallbackQueryHandler(track_deal_callback, pattern="^track_deal_"))
    app.add_handler(CallbackQueryHandler(search_track_callback_handler, pattern="^track_"))

    # Register explore wizard
    explore_wizard = ConversationHandler(
        entry_points=[CommandHandler("explore", start_explore_wizard)],
        states={
            EXPLORE_ORIGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_explore_origin_input),
                CallbackQueryHandler(select_explore_origin_callback, pattern="^expl_org_")
            ],
            EXPLORE_REGION: [
                CallbackQueryHandler(select_explore_region_callback, pattern="^expl_reg_")
            ],
            EXPLORE_BUDGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_explore_budget_input),
                CallbackQueryHandler(select_explore_budget_callback, pattern="^expl_bud_")
            ],
            EXPLORE_LIMIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_explore_limit_input),
                CallbackQueryHandler(select_explore_limit_callback, pattern="^expl_lim_")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel_callback, pattern="^cancel_wizard$")
        ],
        per_chat=True,
        per_user=True
    )
    app.add_handler(explore_wizard)

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
            SEARCH_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_date),
                CallbackQueryHandler(handle_search_date_preset_callback, pattern="^src_datepreset_")
            ],
            SEARCH_FLIGHT_TYPE: [CallbackQueryHandler(select_search_flight_type_callback, pattern="^src_fl_type_")]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel_callback, pattern="^cancel_wizard$")
        ],
        per_chat=True,
        per_user=True
    )
    app.add_handler(search_wizard)

    # Register track wizard (support both /track and /newtrack)
    track_wizard = ConversationHandler(
        entry_points=[CommandHandler("track", start_newtrack), CommandHandler("newtrack", start_newtrack)],
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
            FLIGHT_TYPE: [CallbackQueryHandler(select_flight_type_callback, pattern="^fl_type_")],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_budget)],
            FREQUENCY: [CallbackQueryHandler(select_frequency_callback, pattern="^freq_")]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel_callback, pattern="^cancel_wizard$")
        ],
        per_chat=True,
        per_user=True
    )
    app.add_handler(track_wizard)

    # Register general text input handler (after ConversationHandlers so wizards take priority)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_budget_input))


    print("🤖 Fare Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
