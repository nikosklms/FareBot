"""/digest wizard and shortcut: a weekly explore report delivered on a chosen day and time."""
import re
from typing import Optional

from telegram import Update
from telegram.ext import CommandHandler, ConversationHandler, MessageHandler

from bot.formatting import budget_text, digest_card
from bot.keyboards import DEFAULT_RESULT_LIMIT, button, markup, pairs, quick_origins, regions, result_limits, sort_modes
from bot.services import get_services
from bot.wizard import (
    TEXT, Context, Steps, airport_step, choice_step, draft, respond, start_draft, timeframe_keyboard,
    timeframe_step,
    wizard_conversation,
)
from config import MAX_TRACKERS_PER_USER
from daemon.scheduler import schedule_digest
from database.models import WEEKDAYS, Digest
from services.airports_data import REGION_LABELS, region_display_name
from utils.date_parser import describe_window

ORIGIN, REGION, SORT, BUDGET, WINDOW, DAY, TIME, LIMIT = range(8)
DRAFT = "digest"
BUDGET_OPTIONS = [50, 80, 100, 150]
DAY_OPTIONS = [14, 30, 60, 90]
DEFAULT_DAYS = 30
TIME_OPTIONS = ["09:00", "12:00", "15:00", "18:00", "21:00"]
MAX_RESULTS = 20
CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
USAGE = ("Usage: <code>/digest ATH europe [days] [budget] [Day@HH:MM] [results]</code>\n"
         f"Regions: {', '.join(REGION_LABELS)}")


def parse_clock(text: str) -> Optional[str]:
    match = CLOCK.match(text.strip())
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else None


def parse_weekday(text: str) -> Optional[str]:
    return next((day for day in WEEKDAYS if day.lower() == text.strip().lower()), None)


async def start(update: Update, context: Context) -> int:
    if context.args:
        await _shortcut(update, context, context.args)
        return ConversationHandler.END
    start_draft(context, DRAFT)
    return await STEPS.first(update, context)


async def _shortcut(update: Update, context: Context, args: list[str]) -> None:
    """ORIGIN REGION [DAYS] [BUDGET] [Day@HH:MM] [RESULTS]"""
    region = args[1].lower() if len(args) > 1 else ""
    rest = args[2:]
    schedule = next((a for a in rest if "@" in a), "Sunday@15:00")
    numbers = [a for a in rest if "@" not in a]
    day, _, clock = schedule.partition("@")
    day, clock = parse_weekday(day), parse_clock(clock)
    if (region not in REGION_LABELS or not day or not clock or len(numbers) > 3
            or not all(n.replace(".", "", 1).isdigit() for n in numbers)):
        await update.message.reply_text(USAGE)
        return
    matches = get_services(context).resolver.resolve(args[0])
    if not matches:
        await update.message.reply_text(f"❌ I don't know '{args[0]}'.")
        return
    days = int(float(numbers[0])) if numbers else DEFAULT_DAYS
    budget = float(numbers[1]) if len(numbers) > 1 else 0
    limit = int(float(numbers[2])) if len(numbers) > 2 else DEFAULT_RESULT_LIMIT
    await create_digest(update, context, {
        "origin": matches[0][0], "region": region, "sort": "both", "budget": budget or None,
        "days": max(1, days), "start": None, "end": None, "day": day, "time": clock,
        "limit": min(max(limit, 1), MAX_RESULTS),
    })


async def ask_origin(update: Update, context: Context) -> int:
    await respond(update, "🗞️ <b>Weekly flight deal digest</b>\n\n🛫 <b>Step 1/8</b>: Pick an origin airport or type "
                          "a city name:", quick_origins("dig:org"))
    return ORIGIN


async def ask_region(update: Update, context: Context) -> int:
    await respond(update, f"🛫 <b>From</b>: {draft(context, DRAFT)['origin']}\n\n🌍 <b>Step 2/8</b>: Which region?",
                  regions("dig:reg"))
    return REGION


async def ask_sort(update: Update, context: Context) -> int:
    await respond(update, f"🌍 <b>Region</b>: {region_display_name(draft(context, DRAFT)['region'])}\n\n"
                          "📊 <b>Step 3/8</b>: How should deals be ranked?", sort_modes("dig:sort", default="both"))
    return SORT


async def ask_budget(update: Update, context: Context) -> int:
    budgets = [button(f"€{amount}", f"dig:bud:{amount}") for amount in BUDGET_OPTIONS]
    await respond(update, "🎯 <b>Step 4/8</b>: Maximum price per flight? Tap a button or type an amount in EUR:",
                  markup(*pairs(budgets), [button("Any Budget 💶", "dig:bud:0")], back=True))
    return BUDGET


async def ask_window(update: Update, context: Context) -> int:
    await respond(update, f"🎯 <b>Budget</b>: {budget_text(draft(context, DRAFT)['budget'])}\n\n"
                          "📅 <b>Step 5/8</b>: Which departures should each digest cover? Tap or type a number of "
                          "days ahead, or pick fixed dates on the calendar:",
                  timeframe_keyboard("dig:when", DAY_OPTIONS, DEFAULT_DAYS))
    return WINDOW


async def ask_day(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    window = f"next {d['days']} days" if d["days"] else describe_window(d["start"], d["end"])
    days = [button(f"{day} (Default)" if day == "Sunday" else day, f"dig:day:{day}") for day in WEEKDAYS]
    await respond(update, f"📅 <b>Departures</b>: {window}\n\n⏰ <b>Step 6/8</b>: Which day should it arrive?",
                  markup(*pairs(days), back=True))
    return DAY


async def ask_time(update: Update, context: Context) -> int:
    times = [button(f"{t} (Default)" if t == "15:00" else t, f"dig:time:{t}") for t in TIME_OPTIONS]
    await respond(update, f"⏰ <b>Day</b>: {draft(context, DRAFT)['day']}\n\n🕒 <b>Step 7/8</b>: What time? "
                          "Tap or type <code>HH:MM</code>:", markup(*pairs(times), back=True))
    return TIME


async def ask_limit(update: Update, context: Context) -> int:
    await respond(update, f"🕒 <b>Time</b>: {draft(context, DRAFT)['time']}\n\n📊 <b>Step 8/8</b>: How many deals "
                          f"per digest? (1–{MAX_RESULTS})", result_limits("dig:lim"))
    return LIMIT


async def origin_picked(update: Update, context: Context, code: str) -> int:
    draft(context, DRAFT)["origin"] = code
    return await STEPS.next(update, context)


async def region_picked(update: Update, context: Context, region: str) -> int:
    draft(context, DRAFT)["region"] = region
    return await STEPS.next(update, context)


async def sort_picked(update: Update, context: Context, sort_mode: str) -> int:
    draft(context, DRAFT)["sort"] = sort_mode
    return await STEPS.next(update, context)


async def budget_picked(update: Update, context: Context, value: str) -> int:
    draft(context, DRAFT)["budget"] = float(value) or None
    return await STEPS.next(update, context)


async def budget_typed(update: Update, context: Context) -> int:
    try:
        budget = float(update.message.text.strip().replace("€", ""))
    except ValueError:
        budget = -1
    if budget < 0:
        await update.message.reply_text("❌ Type an amount like <code>80</code>, or <code>0</code> for any budget.",
                                        reply_markup=markup(back=True))
        return BUDGET
    return await budget_picked(update, context, str(budget))


async def days_picked(update: Update, context: Context, days: int) -> int:
    d = draft(context, DRAFT)
    d["days"], d["start"], d["end"] = days, None, None
    return await STEPS.next(update, context)


async def dates_picked(update: Update, context: Context, start_date: str, end_date: Optional[str]) -> int:
    d = draft(context, DRAFT)
    d["days"], d["start"], d["end"] = None, start_date, end_date
    return await STEPS.next(update, context)


async def day_picked(update: Update, context: Context, day: str) -> int:
    draft(context, DRAFT)["day"] = day
    return await STEPS.next(update, context)


async def time_picked(update: Update, context: Context, clock: str) -> int:
    draft(context, DRAFT)["time"] = clock
    return await STEPS.next(update, context)


async def time_typed(update: Update, context: Context) -> int:
    clock = parse_clock(update.message.text)
    if not clock:
        await update.message.reply_text("❌ Type a time like <code>15:00</code>, or tap a button.",
                                        reply_markup=markup(back=True))
        return TIME
    return await time_picked(update, context, clock)


async def limit_picked(update: Update, context: Context, value: str) -> int:
    d = draft(context, DRAFT)
    d["limit"] = int(value)
    await create_digest(update, context, d)
    return ConversationHandler.END


async def limit_typed(update: Update, context: Context) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= MAX_RESULTS:
        await update.message.reply_text(f"❌ Type a number from 1 to {MAX_RESULTS}, or tap a button.",
                                        reply_markup=markup(back=True))
        return LIMIT
    return await limit_picked(update, context, text)


STEPS = Steps(DRAFT, ask_origin, ask_region, ask_sort, ask_budget, ask_window, ask_day, ask_time, ask_limit)


async def create_digest(update: Update, context: Context, d: dict) -> Optional[Digest]:
    services = get_services(context)
    user_id = update.effective_user.id
    existing = await services.db.find_digest(user_id, d["origin"], d["region"], d["days"], d["start"], d["end"])
    if existing:
        await respond(update, f"ℹ️ You already have this digest (#{existing.id}). Manage it in /mytracks.")
        return None
    if await services.db.count_active(user_id) >= MAX_TRACKERS_PER_USER:
        await respond(update, f"⚠️ You already have {MAX_TRACKERS_PER_USER} active trackers and digests. "
                              "Delete or pause one in /mytracks first.")
        return None
    digest = await services.db.create_digest(
        user_id=user_id, origin_code=d["origin"], region=d["region"], max_budget=d["budget"],
        days_ahead=d["days"], departure_date=d["start"], departure_date_end=d["end"], sort_mode=d["sort"],
        delivery_day=d["day"], delivery_time=d["time"], max_results=d["limit"],
    )
    schedule_digest(context.job_queue, digest, services.timezone)
    await respond(update, f"✅ <b>Weekly digest scheduled!</b>\n\n{digest_card(digest)}\n\n"
                          "Manage it anytime in /mytracks.")
    return digest


def conversation() -> ConversationHandler:
    return wizard_conversation("digest", CommandHandler("digest", start), {
        ORIGIN: airport_step("dig:org", ORIGIN, origin_picked, back=False),
        REGION: [choice_step("dig:reg", region_picked, "|".join(REGION_LABELS))],
        SORT: [choice_step("dig:sort", sort_picked, "discount|price|both")],
        BUDGET: [choice_step("dig:bud", budget_picked, r"\d+"), MessageHandler(TEXT, budget_typed)],
        WINDOW: timeframe_step("dig:when", WINDOW, days_picked, dates_picked, STEPS.again),
        DAY: [choice_step("dig:day", day_picked, "|".join(WEEKDAYS))],
        TIME: [choice_step("dig:time", time_picked, r"\d{2}:\d{2}"), MessageHandler(TEXT, time_typed)],
        LIMIT: [choice_step("dig:lim", limit_picked, r"\d+"), MessageHandler(TEXT, limit_typed)],
    }, STEPS)
