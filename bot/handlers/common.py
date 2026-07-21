from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = (
        "✈️ **Welcome to Fare Bot!**\n\n"
        "I monitor flight prices and send you push notifications when prices drop below your target budget.\n\n"
        "**Available Commands:**\n"
        "🔍 `/search` - Instant single flight search\n"
        "🔔 `/newtrack` - Start a background price tracking daemon\n"
        "📋 `/mytracks` - Manage your active tracking daemons\n"
        "❓ `/help` - View this help guide\n\n"
        "Try typing `/search` or `/newtrack` to get started!"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 **Fare Bot User Guide**\n\n"
        "• **Instant Search**: Type `/search` to find current flight options instantly.\n"
        "• **Tracking Daemon**: Type `/newtrack` to set up background price checks (min 6h frequency).\n"
        "• **Notifications**: When a flight drops below your budget, Fare Bot sends an alert and auto-pauses the job.\n"
        "• **Quotas**: You can have up to 5 active background trackers at a time."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode="Markdown")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("❌ Action cancelled.", parse_mode="Markdown")
    return ConversationHandler.END
