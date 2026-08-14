import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from config import DB_PATH
from database.db import DatabaseManager
from daemon.scheduler import schedule_digest_job
from bot.handlers.auth import restricted
from services.resolver import LocationResolver

logger = logging.getLogger(__name__)
db_manager = DatabaseManager(DB_PATH)
resolver = LocationResolver()

DIGEST_ORIGIN, DIGEST_REGION, DIGEST_BUDGET, DIGEST_DAY, DIGEST_TIME, DIGEST_LIMIT = range(6)

@restricted
async def start_digest_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start interactive /digest wizard or execute one-line shortcut if args provided."""
    args = context.args or []

    if len(args) >= 2:
        origin = args[0].upper()
        region = args[1].lower()
        budget = float(args[2]) if len(args) > 2 and args[2].isdigit() else None
        schedule_str = args[3] if len(args) > 3 else "Sunday@15:00"
        limit = int(args[4]) if len(args) > 4 and args[4].isdigit() else 10

        user_id = update.effective_user.id
        dep_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

        if await db_manager.has_active_digest(user_id, origin, f"REGION:{region.upper()}", dep_date):
            await update.message.reply_text(f"⚠️ You already have an active digest for **{origin} → {region.upper()}**!", parse_mode="Markdown")
            return ConversationHandler.END

        digest_tracker_id = await db_manager.create_tracker(
            user_id=user_id,
            origin_code=origin,
            origin_name=origin,
            destination_code=f"REGION:{region.upper()}",
            destination_name=f"{region.capitalize()} Digest",
            departure_date=schedule_str,
            max_budget=budget or 0.0,
            frequency_hours=168
        )

        schedule_digest_job(
            job_queue=context.job_queue,
            tracker_id=digest_tracker_id,
            user_id=user_id,
            origin=origin,
            region=region,
            budget=budget or 0.0,
            schedule_str=schedule_str
        )

        budget_str = f"€{budget:.2f}" if budget else "Any Budget"
        await update.message.reply_text(
            f"✅ **Weekly Digest Scheduled!**\n\n"
            f"🗞️ **Digest #{digest_tracker_id}**: {origin} ✈️ {region.upper()}\n"
            f"🎯 **Target Budget**: {budget_str}\n"
            f"⏰ **Delivery Schedule**: Every {schedule_str}\n"
            f"📊 **Max Deals Limit**: {limit}\n\n"
            f"You can view or manage your scheduled digest anytime in `/mytracks`!",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Start multi-step wizard
    context.user_data.clear()
    buttons = [
        [InlineKeyboardButton("ATH - Athens", callback_data="dig_org_ATH_Athens"), InlineKeyboardButton("SKG - Thessaloniki", callback_data="dig_org_SKG_Thessaloniki")],
        [InlineKeyboardButton("HER - Heraklion", callback_data="dig_org_HER_Heraklion"), InlineKeyboardButton("LON - London", callback_data="dig_org_LON_London")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    await update.message.reply_text(
        "🗞️ **Weekly Flight Deal Digest Wizard**\n\n"
        "🛫 **Step 1/6**: Select origin airport for weekly digest:\n"
        "Select a quick origin airport below or type city/airport name (e.g., 'Athens', 'ATH'):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return DIGEST_ORIGIN

@restricted
async def handle_digest_origin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    matches = resolver.resolve(text)

    if not matches:
        await update.message.reply_text("❌ Location not recognized. Please try typing another city or airport name.")
        return DIGEST_ORIGIN

    buttons = [
        [InlineKeyboardButton(f"{iata} - {name} ({country})", callback_data=f"dig_org_{iata}_{name}")]
        for iata, name, country, score in matches[:4]
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")])

    await update.message.reply_text("Please confirm your origin airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return DIGEST_ORIGIN

@restricted
async def select_digest_origin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["digest_origin"] = iata

    buttons = [
        [InlineKeyboardButton("🇪🇺 Europe", callback_data="dig_reg_europe"), InlineKeyboardButton("🏝️ Greek Islands", callback_data="dig_reg_islands")],
        [InlineKeyboardButton("🕌 Middle East", callback_data="dig_reg_middle_east"), InlineKeyboardButton("⛩️ Asia", callback_data="dig_reg_asia")],
        [InlineKeyboardButton("🌍 Africa", callback_data="dig_reg_africa"), InlineKeyboardButton("🦘 Oceania", callback_data="dig_reg_oceania")],
        [InlineKeyboardButton("💃 Latin America", callback_data="dig_reg_latin_america"), InlineKeyboardButton("🗽 North America", callback_data="dig_reg_north_america")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    await query.message.edit_text(
        f"✅ Origin set to: **{iata} - {name}**\n\n"
        "🌍 **Step 2/6**: Select a destination region for weekly digest:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return DIGEST_REGION

@restricted
async def select_digest_region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    region = query.data.split("_", 2)[2]
    context.user_data["digest_region"] = region

    buttons = [
        [InlineKeyboardButton("€50", callback_data="dig_bud_50"), InlineKeyboardButton("€80", callback_data="dig_bud_80"), InlineKeyboardButton("€100", callback_data="dig_bud_100")],
        [InlineKeyboardButton("€150", callback_data="dig_bud_150"), InlineKeyboardButton("Any Budget 💶", callback_data="dig_bud_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    await query.message.edit_text(
        f"✅ Region set to: **{region.upper().replace('_', ' ')}**\n\n"
        "🎯 **Step 3/6**: Select maximum target budget threshold (or type amount in EUR, e.g. '80'):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return DIGEST_BUDGET

@restricted
async def handle_digest_budget_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        val = float(text)
        budget = val if val > 0 else None
    except ValueError:
        await update.message.reply_text("❌ Invalid budget amount. Please type a positive number (e.g. '80') or tap a button below.")
        return DIGEST_BUDGET

    context.user_data["digest_budget"] = budget
    return await _ask_digest_day(update.message, context)

@restricted
async def select_digest_budget_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    val = float(query.data.split("_")[2])
    context.user_data["digest_budget"] = val if val > 0 else None
    return await _ask_digest_day(query.message, context, is_callback=True)

async def _ask_digest_day(message, context: ContextTypes.DEFAULT_TYPE, is_callback: bool = False) -> int:
    budget = context.user_data.get("digest_budget")
    bud_str = f"€{budget:.2f}" if budget else "Any Budget"

    buttons = [
        [InlineKeyboardButton("Sunday (Default)", callback_data="dig_day_Sunday"), InlineKeyboardButton("Monday", callback_data="dig_day_Monday")],
        [InlineKeyboardButton("Wednesday", callback_data="dig_day_Wednesday"), InlineKeyboardButton("Friday", callback_data="dig_day_Friday")],
        [InlineKeyboardButton("Saturday", callback_data="dig_day_Saturday")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    msg_text = (
        f"✅ Target Budget set to: **{bud_str}**\n\n"
        "📅 **Step 4/6**: Select weekly delivery day of week:"
    )

    if is_callback:
        await message.edit_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message.reply_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    return DIGEST_DAY

@restricted
async def select_digest_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    day = query.data.split("_")[2]
    context.user_data["digest_day"] = day

    buttons = [
        [InlineKeyboardButton("09:00", callback_data="dig_time_09:00"), InlineKeyboardButton("12:00", callback_data="dig_time_12:00")],
        [InlineKeyboardButton("15:00 (Default)", callback_data="dig_time_15:00"), InlineKeyboardButton("18:00", callback_data="dig_time_18:00")],
        [InlineKeyboardButton("21:00", callback_data="dig_time_21:00")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    await query.message.edit_text(
        f"✅ Delivery Day set to: **{day}**\n\n"
        "⏰ **Step 5/6**: Select weekly delivery time of day (or type HH:MM format, e.g. '15:00'):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return DIGEST_TIME

@restricted
async def handle_digest_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if ":" not in text:
        await update.message.reply_text("❌ Please enter time in HH:MM format (e.g. '15:00') or tap a button below.")
        return DIGEST_TIME

    context.user_data["digest_time"] = text
    return await _ask_digest_limit(update.message, context)

@restricted
async def select_digest_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    time_str = query.data.split("_")[2]
    context.user_data["digest_time"] = time_str
    return await _ask_digest_limit(query.message, context, is_callback=True)

async def _ask_digest_limit(message, context: ContextTypes.DEFAULT_TYPE, is_callback: bool = False) -> int:
    time_str = context.user_data.get("digest_time", "15:00")

    buttons = [
        [InlineKeyboardButton("5", callback_data="dig_lim_5"), InlineKeyboardButton("10 (Default)", callback_data="dig_lim_10")],
        [InlineKeyboardButton("15", callback_data="dig_lim_15"), InlineKeyboardButton("20", callback_data="dig_lim_20")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    msg_text = (
        f"✅ Delivery Time set to: **{time_str}**\n\n"
        "📊 **Step 6/6**: How many top flight deal results would you like in each weekly digest? (1 to 20, default 10):"
    )

    if is_callback:
        await message.edit_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message.reply_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    return DIGEST_LIMIT

@restricted
async def handle_digest_limit_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 20):
        await update.message.reply_text("❌ Please enter a number between 1 and 20 (or tap a button below).")
        return DIGEST_LIMIT

    limit = int(text)
    user_id = update.effective_user.id
    return await _execute_wizard_digest(update.message, context, user_id, limit)

@restricted
async def select_digest_limit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    limit = int(query.data.split("_")[2])
    user_id = update.effective_user.id
    return await _execute_wizard_digest(query.message, context, user_id, limit, is_callback=True)

async def _execute_wizard_digest(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, limit: int, is_callback: bool = False) -> int:
    origin = context.user_data.get("digest_origin", "ATH")
    region = context.user_data.get("digest_region", "europe")
    budget = context.user_data.get("digest_budget")
    day = context.user_data.get("digest_day", "Sunday")
    time_str = context.user_data.get("digest_time", "15:00")
    schedule_str = f"{day}@{time_str}"

    dep_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    if await db_manager.has_active_digest(user_id, origin, f"REGION:{region.upper()}", dep_date):
        warn_text = f"⚠️ You already have an active digest for **{origin} → {region.upper()}**!"
        if is_callback:
            await message.edit_text(warn_text, parse_mode="Markdown")
        else:
            await message.reply_text(warn_text, parse_mode="Markdown")
        context.user_data.clear()
        return ConversationHandler.END

    digest_tracker_id = await db_manager.create_tracker(
        user_id=user_id,
        origin_code=origin,
        origin_name=origin,
        destination_code=f"REGION:{region.upper()}",
        destination_name=f"{region.capitalize()} Digest",
        departure_date=schedule_str,
        max_budget=budget or 0.0,
        frequency_hours=168
    )

    schedule_digest_job(
        job_queue=context.job_queue,
        tracker_id=digest_tracker_id,
        user_id=user_id,
        origin=origin,
        region=region,
        budget=budget or 0.0,
        schedule_str=schedule_str
    )

    budget_str = f"€{budget:.2f}" if budget else "Any Budget"
    success_text = (
        f"✅ **Weekly Digest Scheduled!**\n\n"
        f"🗞️ **Digest #{digest_tracker_id}**: {origin} ✈️ {region.upper()}\n"
        f"🎯 **Target Budget**: {budget_str}\n"
        f"📅 **Delivery Schedule**: Every {day} at {time_str}\n"
        f"📊 **Max Deals Limit**: {limit}\n\n"
        f"You can view, edit budget, pause, or delete your scheduled digest anytime in `/mytracks`!"
    )

    if is_callback:
        await message.edit_text(success_text, parse_mode="Markdown")
    else:
        await message.reply_text(success_text, parse_mode="Markdown")

    context.user_data.clear()
    return ConversationHandler.END
