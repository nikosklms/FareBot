from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from bot.handlers.auth import restricted

@restricted
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = (
        "✈️ **Welcome to Fare Bot!**\n\n"
        "I search flights & track price drops with automatic background alerts.\n\n"
        "**Available Commands:**\n"
        "🌟 `/explore` - Interactive wizard for top discount flight deals by region\n"
        "🗞️ `/digest` - Interactive wizard for weekly recurring flight deal digests\n"
        "🔍 `/search` - Instant flight search (Single date or Date range)\n"
        "🔔 `/track` or `/newtrack` - Start background price tracking\n"
        "📊 `/mytracks` - Manage active price trackers, digests & edit budgets\n"
        "❓ `/help` - View complete guide and syntax examples\n\n"
        "**Quick Shortcuts:**\n"
        "• Deal Discovery: `/explore ATH europe 100 10`\n"
        "• Weekly Digest: `/digest ATH europe 80 Sunday@15:00 10`\n"
        "• Range Search: `/search ATH LON 2026-09-01..2026-09-15`\n"
        "• Range Track: `/track ATH LON 2026-09-01..2026-09-15 150`"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown")

@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 **Fare Bot User Guide**\n\n"
        "🌟 **Deal Discovery (`/explore`)**\n"
        "• Interactive wizard: `/explore` (Step-by-step origin, region, budget, and results count limit 1-20)\n"
        "• Direct shortcut: `/explore ATH europe 100 10`\n"
        "• 1-Tap Track buttons automatically set a target budget **10% below deal price**!\n\n"
        "🗞️ **Weekly Digest (`/digest`)**\n"
        "• Interactive wizard: `/digest` (Step-by-step origin, region, budget, day of week, time of day & limit)\n"
        "• Direct shortcut: `/digest ATH europe 80 Sunday@15:00 10`\n"
        "• Customize exact weekly delivery day (e.g., Sunday) and delivery time (e.g., 15:00).\n\n"
        "🔍 **Instant Search (`/search`)**\n"
        "• Interactive wizard: `/search` (step-by-step with interactive calendar picker)\n"
        "• Direct shortcut single date: `/search ATH LON 2026-09-01`\n"
        "• Direct shortcut date range: `/search ATH LON 2026-09-01..2026-09-15`\n\n"
        "🔔 **Price Tracker (`/track` or `/newtrack`)**\n"
        "• Interactive wizard: `/track` (step-by-step with interactive calendar picker)\n"
        "• Direct shortcut single date: `/track ATH LON 2026-09-01 150`\n"
        "• Direct shortcut date range: `/track ATH LON 2026-09-01..2026-09-15 150`\n\n"
        "📅 **Interactive Calendar & Date Formats:**\n"
        "• Interactive 7-column calendar widget with month navigation (`«` / `»`)\n"
        "• `2026-09-01..2026-09-15` or `2026-09-01:2026-09-15`\n\n"
        "📊 **Management (`/mytracks`)**\n"
        "• View, edit target budgets, pause, resume, or delete your active trackers and weekly digests (up to 20 max)."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode="Markdown")

@restricted
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("❌ Action cancelled.", parse_mode="Markdown")
    return ConversationHandler.END

@restricted
async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        if query.message and hasattr(query.message, "edit_text"):
            await query.message.edit_text("❌ Action cancelled.")
    return ConversationHandler.END
