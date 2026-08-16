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
    handle_date_preset_callback,
    handle_calendar_date_selection,
    open_calendar_track_callback,
    calendar_nav_callback,
    track_calendar_mode_callback,
    track_calendar_ignore_callback,
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
    select_explore_sort_callback,
    handle_explore_timeframe_input,
    select_explore_timeframe_callback,
    open_calendar_explore_callback,
    explore_calendar_nav_callback,
    explore_calendar_mode_callback,
    explore_calendar_ignore_callback,
    handle_explore_calendar_date_selection,
    handle_explore_limit_input,
    select_explore_limit_callback,
    EXPLORE_ORIGIN,
    EXPLORE_REGION,
    EXPLORE_SORT,
    EXPLORE_TIMEFRAME,
    EXPLORE_LIMIT,
    start_digest_wizard,
    handle_digest_origin_input,
    select_digest_origin_callback,
    select_digest_region_callback,
    select_digest_sort_callback,
    handle_digest_budget_input,
    select_digest_budget_callback,
    handle_digest_timeframe_input,
    select_digest_timeframe_callback,
    open_calendar_digest_callback,
    digest_calendar_nav_callback,
    digest_calendar_mode_callback,
    digest_calendar_ignore_callback,
    handle_digest_calendar_date_selection,
    select_digest_day_callback,
    handle_digest_time_input,
    select_digest_time_callback,
    handle_digest_limit_input,
    select_digest_limit_callback,
    DIGEST_ORIGIN,
    DIGEST_REGION,
    DIGEST_SORT,
    DIGEST_BUDGET,
    DIGEST_TIMEFRAME,
    DIGEST_DAY,
    DIGEST_TIME,
    DIGEST_LIMIT,
    track_deal_callback,
    search_command,
    handle_search_origin,
    select_search_origin_callback,
    handle_search_destination,
    select_search_destination_callback,
    handle_search_date,
    handle_search_date_preset_callback,
    open_calendar_search_callback,
    handle_search_calendar_date_selection,
    search_calendar_nav_callback,
    search_calendar_mode_callback,
    search_calendar_ignore_callback,
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

import fcntl
import sys

def ensure_single_instance():
    lock_file_path = os.path.join(os.path.dirname(__file__), "farebot.lock")
    try:
        lock_file = open(lock_file_path, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        globals()["_instance_lock_file"] = lock_file
    except IOError:
        logger.error("❌ Another instance of FareBot is already running. Exiting.")
        sys.exit(1)

def main():
    ensure_single_instance()
    check_config()
    init_db()
    start_health_check_server()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mytracks", mytracks_command))
    app.add_handler(CallbackQueryHandler(dashboard_callback_handler, pattern="^dash_"))
    app.add_handler(CallbackQueryHandler(track_deal_callback, pattern="^track_deal_"))
    app.add_handler(CallbackQueryHandler(search_track_callback_handler, pattern="^track_"))

    # Register digest wizard
    digest_wizard = ConversationHandler(
        entry_points=[CommandHandler("digest", start_digest_wizard)],
        states={
            DIGEST_ORIGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_digest_origin_input),
                CallbackQueryHandler(select_digest_origin_callback, pattern="^dig_org_")
            ],
            DIGEST_REGION: [
                CallbackQueryHandler(select_digest_region_callback, pattern="^dig_reg_")
            ],
            DIGEST_SORT: [
                CallbackQueryHandler(select_digest_sort_callback, pattern="^dig_sort_")
            ],
            DIGEST_BUDGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_digest_budget_input),
                CallbackQueryHandler(select_digest_budget_callback, pattern="^dig_bud_")
            ],
            DIGEST_TIMEFRAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_digest_timeframe_input),
                CallbackQueryHandler(open_calendar_digest_callback, pattern="^open_cal_digest$"),
                CallbackQueryHandler(digest_calendar_nav_callback, pattern="^cal_nav_"),
                CallbackQueryHandler(digest_calendar_mode_callback, pattern="^cal_mode_"),
                CallbackQueryHandler(digest_calendar_ignore_callback, pattern="^cal_ignore$"),
                CallbackQueryHandler(handle_digest_calendar_date_selection, pattern="^cal_day_"),
                CallbackQueryHandler(select_digest_timeframe_callback, pattern="^dig_tf_")
            ],
            DIGEST_DAY: [
                CallbackQueryHandler(select_digest_day_callback, pattern="^dig_day_")
            ],
            DIGEST_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_digest_time_input),
                CallbackQueryHandler(select_digest_time_callback, pattern="^dig_time_")
            ],
            DIGEST_LIMIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_digest_limit_input),
                CallbackQueryHandler(select_digest_limit_callback, pattern="^dig_lim_")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel_callback, pattern="^cancel_wizard$")
        ],
        per_chat=True,
        per_user=True,
        per_message=False
    )
    app.add_handler(digest_wizard)

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
            EXPLORE_SORT: [
                CallbackQueryHandler(select_explore_sort_callback, pattern="^expl_sort_")
            ],
            EXPLORE_TIMEFRAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_explore_timeframe_input),
                CallbackQueryHandler(open_calendar_explore_callback, pattern="^open_cal_explore$"),
                CallbackQueryHandler(explore_calendar_nav_callback, pattern="^cal_nav_"),
                CallbackQueryHandler(explore_calendar_mode_callback, pattern="^cal_mode_"),
                CallbackQueryHandler(explore_calendar_ignore_callback, pattern="^cal_ignore$"),
                CallbackQueryHandler(handle_explore_calendar_date_selection, pattern="^cal_day_"),
                CallbackQueryHandler(select_explore_timeframe_callback, pattern="^expl_tf_")
            ],
            EXPLORE_LIMIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_explore_limit_input),
                CallbackQueryHandler(select_explore_limit_callback, pattern="^expl_lim_")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel_callback, pattern="^(cancel_wizard|cal_cancel)$")
        ],
        per_chat=True,
        per_user=True,
        per_message=False
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
                CallbackQueryHandler(open_calendar_search_callback, pattern="^open_cal_search$"),
                CallbackQueryHandler(handle_search_date_preset_callback, pattern="^src_datepreset_"),
                CallbackQueryHandler(search_calendar_nav_callback, pattern="^cal_nav_"),
                CallbackQueryHandler(search_calendar_mode_callback, pattern="^cal_mode_"),
                CallbackQueryHandler(search_calendar_ignore_callback, pattern="^cal_ignore$"),
                CallbackQueryHandler(handle_search_calendar_date_selection, pattern="^cal_day_")
            ],
            SEARCH_FLIGHT_TYPE: [CallbackQueryHandler(select_search_flight_type_callback, pattern="^src_fl_type_")]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel_callback, pattern="^(cancel_wizard|cal_cancel)$")
        ],
        per_chat=True,
        per_user=True,
        per_message=False
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
            DEPARTURE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_departure_date),
                CallbackQueryHandler(open_calendar_track_callback, pattern="^open_cal_track$"),
                CallbackQueryHandler(handle_date_preset_callback, pattern="^datepreset_"),
                CallbackQueryHandler(calendar_nav_callback, pattern="^cal_nav_"),
                CallbackQueryHandler(track_calendar_mode_callback, pattern="^cal_mode_"),
                CallbackQueryHandler(track_calendar_ignore_callback, pattern="^cal_ignore$"),
                CallbackQueryHandler(handle_calendar_date_selection, pattern="^cal_day_")
            ],
            FLIGHT_TYPE: [CallbackQueryHandler(select_flight_type_callback, pattern="^fl_type_")],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_budget)],
            FREQUENCY: [CallbackQueryHandler(select_frequency_callback, pattern="^freq_")]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel_callback, pattern="^(cancel_wizard|cal_cancel)$")
        ],
        per_chat=True,
        per_user=True,
        per_message=False
    )
    app.add_handler(track_wizard)

    # Register general text input handler (after ConversationHandlers so wizards take priority)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_budget_input))


    print("🤖 Fare Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
