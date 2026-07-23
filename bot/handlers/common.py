from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from bot.handlers.auth import restricted

@restricted
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = (
        "✈️ **Welcome to Fare Bot!**\n\n"
        "I search flights & track price drops with automatic background alerts.\n\n"
        "**Available Commands:**\n"
        "🔍 `/search` - Instant flight search (Single date or Date range)\n"
        "🔔 `/track` or `/newtrack` - Start background price tracking\n"
        "📊 `/mytracks` - Manage active price trackers\n"
        "❓ `/help` - View complete guide and syntax examples\n\n"
        "**Quick Examples:**\n"
        "• Range Search: `/search ATH LON 2026-09-01..2026-09-15`\n"
        "• Range Track: `/track ATH LON 2026-09-01..2026-09-15 150`"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown")

@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 **Fare Bot User Guide**\n\n"
        "🔍 **Instant Search (`/search`)**\n"
        "• Interactive wizard: `/search` (step-by-step with quick preset buttons)\n"
        "• One-line single date: `/search ATH LON 2026-09-01`\n"
        "• One-line date range: `/search ATH LON 2026-09-01..2026-09-15`\n\n"
        "🔔 **Price Tracker (`/track` or `/newtrack`)**\n"
        "• Interactive wizard: `/track` (step-by-step with preset date buttons)\n"
        "• One-line single date: `/track ATH LON 2026-09-01 150`\n"
        "• One-line date range: `/track ATH LON 2026-09-01..2026-09-15 150`\n\n"
        "📅 **Supported Date Range Formats:**\n"
        "• `2026-09-01..2026-09-15` or `2026-09-01:2026-09-15`\n"
        "• `2026-09-01 to 2026-09-15` or `2026-09-01 - 2026-09-15`\n"
        "• Quick preset buttons in wizard: `[Next 7 Days]`, `[Next 14 Days]`, `[This Weekend]`\n\n"
        "📊 **Management (`/mytracks`)**\n"
        "• View, pause, resume, or delete your active trackers (up to 5 max)."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode="Markdown")

@restricted
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("❌ Action cancelled.", parse_mode="Markdown")
    return ConversationHandler.END
