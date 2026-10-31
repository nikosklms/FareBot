import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.handlers.share import open_shared
from bot.wizard import CALENDAR_KEY, cancel_running_task
from bot.auth import max_active

logger = logging.getLogger(__name__)


START_TEXT = """✈️ <b>Welcome to Fare Bot!</b>

I search Google Flights and watch prices for you in the background.

<b>Commands</b>
🔍 /search - Search flights for a date or date range
🔔 /track - Get an alert when a route drops below your budget
🌟 /explore - Find the best deals from an airport to a whole region
🗞️ /digest - Get a weekly deal report on a day and time you choose
📊 /mytracks - Manage your trackers and digests
❓ /help - Shortcuts and examples
❌ /cancel - Stop the current wizard or search"""

HELP_TEXT = """📖 <b>Fare Bot Guide</b>

Every command starts a step-by-step wizard. Add arguments to skip it:

🔍 <b>Search</b>
<code>/search ATH LON 2026-09-01</code>
<code>/search ATH LON 2026-09-01..2026-09-15 direct</code>

🔔 <b>Track</b> (checks every 6 hours)
<code>/track ATH LON 2026-09-01 150</code>
<code>/track ATH LON 2026-09-01..2026-09-15 150 direct</code>

🌟 <b>Explore</b>: origin, region, then optional days ahead (default 30), budget (0 = any) and number of results (default 10)
<code>/explore ATH europe 30 100 10</code>
Tracking a deal sets the target budget 10% below its price.

🗞️ <b>Digest</b>: origin, region, then optional days ahead, budget, delivery day@time and number of results
<code>/digest ATH europe 30 80 Sunday@15:00 10</code>

🌍 <b>Regions</b>: europe, islands, middle_east, asia, africa, oceania, latin_america, north_america

📅 <b>Dates</b>: <code>2026-09-01</code> or a range <code>2026-09-01..2026-09-15</code>

📊 /mytracks lets you pause, resume, edit (dates, budget, schedule and more), share or delete your trackers and digests (up to {active} active).

⬅️ Every wizard step has a Back button."""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:  # opened through a share link
        await open_shared(update, context, context.args[0])
        return
    await update.message.reply_text(START_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT.format(active=max_active(update.effective_user.id)))


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global /cancel; any open wizard also ends because it sees a command."""
    stopped = cancel_running_task(context)
    context.user_data.pop(CALENDAR_KEY, None)
    await update.message.reply_text("❌ Cancelled." + (" The running search was stopped." if stopped else ""))


async def stop_task_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    stopped = cancel_running_task(context)
    await query.answer("Stopping…" if stopped else "Nothing is running.")


async def noop_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error while processing an update", exc_info=context.error)
    if isinstance(context.error, BadRequest) and "not modified" in str(context.error):
        return
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id, "⚠️ Something went wrong. Please try again.")
        except Exception:
            logger.warning("Could not notify user about the error", exc_info=True)
