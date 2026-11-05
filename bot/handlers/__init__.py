from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, TypeHandler

from bot.auth import auth_gate
from bot.deal_buttons import toggle_deals_handler
from bot.handlers import access, dashboard, digest, edit, explore, limits, search, share, stats, track
from bot.handlers.common import (
    cancel_command, error_handler, help_command, noop_pressed, start_command, stop_task_pressed,
)
from bot.keyboards import NOOP, STOP_TASK

BOT_COMMANDS = [
    ("search", "🔍 Search flights"),
    ("track", "🔔 Track a route's price"),
    ("explore", "🌟 Find deals to a region"),
    ("digest", "🗞️ Weekly deal digest"),
    ("mytracks", "📊 Manage trackers and digests"),
    ("help", "❓ Help and shortcuts"),
    ("cancel", "❌ Cancel the current action"),
]
ADMIN_COMMANDS = [("users", "👥 Approve and manage users"), ("limits", "⚙️ Set trackers and days limits"),
                  ("stats", "📈 Searches, cache and users")]


def register_handlers(app: Application) -> None:
    """Group -1 checks access, group 0 holds global handlers, and each wizard gets its own
    group so that starting one wizard ends any other that was open."""
    app.add_handler(TypeHandler(Update, auth_gate), group=-1)
    app.add_handlers([
        CommandHandler("start", start_command),
        CommandHandler("help", help_command),
        CommandHandler("cancel", cancel_command),
        CommandHandler("mytracks", dashboard.mytracks_command),
        dashboard.dashboard_handler,
        track.track_button_handler,
        toggle_deals_handler,
        *share.share_handlers,
        *access.access_handlers,
        *limits.limits_handlers,
        stats.stats_handler,
        CallbackQueryHandler(stop_task_pressed, pattern=f"^{STOP_TASK}$"),
        CallbackQueryHandler(noop_pressed, pattern=f"^{NOOP}$"),
    ], group=0)
    for group, wizard in enumerate([search, track, explore, digest, edit, limits], start=1):
        app.add_handler(wizard.conversation(), group=group)
    app.add_error_handler(error_handler)
