"""Editing trackers and digests from /mytracks.

'dash:edit:<kind>:<id>' opens a menu of fields; saving a field shows the menu again so
several things can be changed in one go. 'dash:budget:<kind>:<id>' (the price alert's
'Set Lower Budget' button) goes straight to the budget. Route and region are not
editable: a different route is a different tracker.
"""
from functools import wraps
from typing import Any, Optional

from telegram import Message, Update
from telegram.ext import BaseHandler, CallbackQueryHandler, ConversationHandler, MessageHandler

from bot.formatting import budget_text, digest_card, digest_window_text, eur, flight_type_label, tracker_card
from bot.handlers.dashboard import (
    DIGEST, TRACKER, Item, item_buttons, label_for, load_owned, set_active,
)
from bot.handlers.digest import BUDGET_OPTIONS, DAY_OPTIONS, DEFAULT_DAYS, MAX_RESULTS, TIME_OPTIONS, parse_clock
from bot.handlers.track import FREQUENCIES
from bot.keyboards import RESULT_LIMITS, button, flight_types, markup, pairs, result_limits, sort_modes
from bot.auth import limit_reached
from bot.services import get_services
from bot.wizard import (
    parse_price,
    DATES_PROMPT, TEXT, Context, choice_step, dates_keyboard, dates_step, draft, respond, start_draft,
    timeframe_keyboard, timeframe_step, wizard_conversation,
)
from daemon.scheduler import schedule_digest, schedule_tracker
from database.models import ACTIVE, EXPIRED, PAUSED, WEEKDAYS
from utils.date_parser import describe_window, is_past

MENU, BUDGET, DATES, FLIGHTS, FREQUENCY, WINDOW, SORT, LIMIT, DAY, TIME = range(10)
DRAFT = "edit"

FIELDS = {
    TRACKER: [("dates", "📅 Dates"), ("flights", "⚙️ Flights"), ("budget", "🎯 Budget"), ("frequency", "🔄 Checks")],
    DIGEST: [("budget", "🎯 Budget"), ("window", "📅 Departures"), ("flights", "⚙️ Flights"), ("sort", "📊 Ranking"),
             ("limit", "🔢 Deals Shown"), ("day", "⏰ Day"), ("time", "🕒 Time")],
}


OUT_OF_DATE = "This editor is out of date. Open it again from /mytracks."


async def _item(update: Update, context: Context) -> Optional[Item]:
    d = draft(context, DRAFT)
    return await load_owned(get_services(context), d["kind"], d["id"], update.effective_user.id)


async def _show(update: Update, context: Context, text: str, reply_markup=None) -> None:
    """Show an editor message and remember it: only its buttons act on the item being edited."""
    _remember(context, await respond(update, text, reply_markup))


def _remember(context: Context, message: Message) -> None:
    draft(context, DRAFT)["message_id"] = message.message_id


def _current_message_only(handler: BaseHandler) -> BaseHandler:
    """Buttons on an older editor message (or another item's) would act on whatever is being
    edited now, so they're refused."""
    if isinstance(handler, CallbackQueryHandler):
        inner = handler.callback

        @wraps(inner)
        async def guarded(update: Update, context: Context) -> Optional[int]:
            query = update.callback_query
            if query.message.message_id != draft(context, DRAFT).get("message_id"):
                await query.answer(OUT_OF_DATE, show_alert=True)
                return None
            return await inner(update, context)

        handler.callback = guarded
    return handler


def _card(kind: str, item: Item) -> str:
    return tracker_card(item) if kind == TRACKER else digest_card(item)


# ----------------------------------------------------------------------
# Entry, menu and finishing
# ----------------------------------------------------------------------

async def _open(update: Update, context: Context) -> Optional[Item]:
    query = update.callback_query
    _, _, kind, raw_id = query.data.split(":")
    item = await load_owned(get_services(context), kind, int(raw_id), query.from_user.id)
    if not item:
        await query.answer("This item no longer exists.", show_alert=True)
        return None
    await query.answer()
    d = start_draft(context, DRAFT)
    d["kind"], d["id"], d["message_id"] = kind, item.id, query.message.message_id
    return item


async def open_editor(update: Update, context: Context) -> int:
    if not await _open(update, context):
        return ConversationHandler.END
    return await show_menu(update, context)


async def open_budget(update: Update, context: Context) -> int:
    """From the price alert: ask in a new message so the alert and its offers stay visible."""
    item = await _open(update, context)
    if not item:
        return ConversationHandler.END
    kind = draft(context, DRAFT)["kind"]
    _remember(context, await update.callback_query.message.reply_text(_budget_prompt(kind, item),
                                                                      reply_markup=_budget_markup(kind)))
    return BUDGET


async def show_menu(update: Update, context: Context, note: str = "") -> int:
    item = await _item(update, context)
    if not item:
        await respond(update, "This item no longer exists.")
        return ConversationHandler.END
    kind = draft(context, DRAFT)["kind"]
    fields = [button(label, f"edit:field:{key}") for key, label in FIELDS[kind]]
    await _show(update, context, f"{note}✏️ <b>Editing</b>\n\n{_card(kind, item)}\n\nWhat do you want to change?",
                markup(*pairs(fields), [button("✅ Done", "edit:done")], cancel=False))
    return MENU


async def back_to_menu(update: Update, context: Context) -> int:
    await update.callback_query.answer()
    context.user_data.pop("calendar", None)
    return await show_menu(update, context)


async def done(update: Update, context: Context) -> int:
    await update.callback_query.answer()
    item = await _item(update, context)
    if item:
        kind = draft(context, DRAFT)["kind"]
        await respond(update, _card(kind, item), item_buttons(kind, item))
    return ConversationHandler.END


async def field_picked(update: Update, context: Context, field: str) -> int:
    if not await _item(update, context):
        await respond(update, "This item no longer exists.")
        return ConversationHandler.END
    if field not in dict(FIELDS[draft(context, DRAFT)["kind"]]):
        return MENU  # a digest field on a tracker, or the other way round
    return await ASKS[field](update, context)


async def save(update: Update, context: Context, **changes: Any) -> int:
    """Store the changes, keep scheduling in sync, then show the menu again."""
    services = get_services(context)
    item = await _item(update, context)
    if not item:
        await respond(update, "This item no longer exists.")
        return ConversationHandler.END
    kind = draft(context, DRAFT)["kind"]
    notes = []

    if kind == TRACKER and {"departure_date", "direct_only"} & set(changes):
        new = {**vars(item), **changes}
        twin = await services.db.find_tracker(item.user_id, item.origin_code, item.destination_code,
                                              new["departure_date"], new["departure_date_end"], new["direct_only"],
                                              other_than=item.id)
        if twin:
            return await show_menu(update, context, note=f"ℹ️ Tracker #{twin.id} already watches exactly that, "
                                                         "so I haven't changed this one.\n\n")
    if kind == TRACKER:
        item = await services.db.update_tracker(item.id, **changes)
        if "max_budget" in changes and item.last_price_found and item.last_price_found < item.max_budget:
            notes.append(f"⚠️ The last price found was {eur(item.last_price_found)}, already below this "
                         "budget, so you'll get an alert at the next check.")
        if "max_budget" in changes and item.status == PAUSED:
            notes.append("It was paused, so I've resumed it." if await set_active(services, context, kind, item, True)
                         else limit_reached(item.user_id))
        elif "departure_date" in changes and item.status == EXPIRED and not is_past(item.last_departure_date):
            notes.append("The new dates are in the future, so it's active again."
                         if await set_active(services, context, kind, item, True) else limit_reached(item.user_id))
        elif item.status == ACTIVE:
            schedule_tracker(context.job_queue, item)
    else:
        item = await services.db.update_digest(item.id, **changes)
        window_changed = {"days_ahead", "departure_date"} & set(changes)
        if window_changed and item.status == EXPIRED:
            notes.append("It's active again with the new departures."
                         if await set_active(services, context, kind, item, True) else limit_reached(item.user_id))
        elif item.status == ACTIVE:
            schedule_digest(context.job_queue, item, services.timezone)

    return await show_menu(update, context, note=f"✅ <b>Saved.</b> {' '.join(notes)}\n\n")


# ----------------------------------------------------------------------
# Fields
# ----------------------------------------------------------------------

def _budget_prompt(kind: str, item: Item) -> str:
    hint = " or tap Any Budget" if kind == DIGEST else ""
    return (f"🎯 <b>{label_for(kind, item.id)}</b> budget is now {budget_text(item.max_budget)}.\n\n"
            f"Type the new maximum price in EUR (e.g. <code>45</code>){hint}:")


def _budget_markup(kind: str):
    if kind == DIGEST:
        return markup(*pairs([button(f"€{amount}", f"edit:bud:{amount}") for amount in BUDGET_OPTIONS]),
                      [button("Any Budget 💶", "edit:bud:0")], back=True)
    return markup(back=True)


async def ask_budget(update: Update, context: Context) -> int:
    kind = draft(context, DRAFT)["kind"]
    await _show(update, context, _budget_prompt(kind, await _item(update, context)), _budget_markup(kind))
    return BUDGET


async def budget_typed(update: Update, context: Context) -> int:
    kind = draft(context, DRAFT)["kind"]
    budget = parse_price(update.message.text)
    budget = -1 if budget is None else budget
    if budget < 0 or (budget == 0 and kind == TRACKER):
        await update.message.reply_text("❌ That's not a valid budget. Type a number like <code>45</code>.",
                                        reply_markup=markup(back=True))
        return BUDGET
    if kind == DIGEST and budget == 0:
        return await save(update, context, max_budget=None)  # 0 means any budget
    return await save(update, context, max_budget=budget)


async def budget_picked(update: Update, context: Context, value: str) -> int:
    if draft(context, DRAFT)["kind"] == TRACKER:
        return BUDGET  # only digests get budget buttons; a tracker's budget is typed
    return await save(update, context, max_budget=float(value) or None)


async def ask_dates(update: Update, context: Context) -> int:
    item = await _item(update, context)
    await _show(update, context, f"📅 Now: {describe_window(item.departure_date, item.departure_date_end)}\n\n"
                          f"New dates? {DATES_PROMPT}", dates_keyboard("edit:date"))
    return DATES


async def dates_picked(update: Update, context: Context, start: str, end: Optional[str]) -> int:
    return await save(update, context, departure_date=start, departure_date_end=end)


async def ask_flights(update: Update, context: Context) -> int:
    item = await _item(update, context)
    await _show(update, context, f"⚙️ Now: {flight_type_label(item.direct_only)}\n\nWhich flights should I watch?",
                  flight_types("edit:direct"))
    return FLIGHTS


async def flights_picked(update: Update, context: Context, value: str) -> int:
    return await save(update, context, direct_only=value == "1")


async def ask_frequency(update: Update, context: Context) -> int:
    item = await _item(update, context)
    hours = [[button(f"Every {h} hours", f"edit:freq:{h}")] for h in FREQUENCIES]
    await _show(update, context, f"🔄 Now: every {item.frequency_hours} hours\n\nHow often should I check?",
                  markup(*hours, back=True))
    return FREQUENCY


async def frequency_picked(update: Update, context: Context, value: str) -> int:
    return await save(update, context, frequency_hours=int(value))


async def ask_window(update: Update, context: Context) -> int:
    item = await _item(update, context)
    await _show(update, context, f"📅 Now: {digest_window_text(item)}\n\nWhich departures should each digest cover? "
                          "Tap or type a number of days ahead, or pick fixed dates:",
                  timeframe_keyboard("edit:when", DAY_OPTIONS, DEFAULT_DAYS))
    return WINDOW


async def window_days_picked(update: Update, context: Context, days: int) -> int:
    return await save(update, context, days_ahead=days, departure_date=None, departure_date_end=None)


async def window_dates_picked(update: Update, context: Context, start: str, end: Optional[str]) -> int:
    return await save(update, context, days_ahead=None, departure_date=start, departure_date_end=end)


async def ask_sort(update: Update, context: Context) -> int:
    item = await _item(update, context)
    await _show(update, context, f"📊 Now: {item.sort_mode}\n\nHow should deals be ranked?",
                  sort_modes("edit:sort", default=item.sort_mode))
    return SORT


async def sort_picked(update: Update, context: Context, value: str) -> int:
    return await save(update, context, sort_mode=value)


async def ask_limit(update: Update, context: Context) -> int:
    item = await _item(update, context)
    await _show(update, context, f"🔢 Now: up to {item.max_results} deals\n\nHow many deals per digest? (1–{MAX_RESULTS})",
                  result_limits("edit:lim"))
    return LIMIT


async def limit_picked(update: Update, context: Context, value: str) -> int:
    return await save(update, context, max_results=int(value))


async def limit_typed(update: Update, context: Context) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= MAX_RESULTS:
        await update.message.reply_text(f"❌ Type a number from 1 to {MAX_RESULTS}, or tap a button.",
                                        reply_markup=markup(back=True))
        return LIMIT
    return await limit_picked(update, context, text)


async def ask_day(update: Update, context: Context) -> int:
    item = await _item(update, context)
    days = [button(day, f"edit:day:{day}") for day in WEEKDAYS]
    await _show(update, context, f"⏰ Now: {item.delivery_day}\n\nWhich day should it arrive?", markup(*pairs(days), back=True))
    return DAY


async def day_picked(update: Update, context: Context, day: str) -> int:
    return await save(update, context, delivery_day=day)


async def ask_time(update: Update, context: Context) -> int:
    item = await _item(update, context)
    times = [button(t, f"edit:time:{t}") for t in TIME_OPTIONS]
    await _show(update, context, f"🕒 Now: {item.delivery_time}\n\nWhat time? Tap or type <code>HH:MM</code>:",
                  markup(*pairs(times), back=True))
    return TIME


async def time_picked(update: Update, context: Context, clock: str) -> int:
    return await save(update, context, delivery_time=clock)


async def time_typed(update: Update, context: Context) -> int:
    clock = parse_clock(update.message.text)
    if not clock:
        await update.message.reply_text("❌ Type a time like <code>15:00</code>, or tap a button.",
                                        reply_markup=markup(back=True))
        return TIME
    return await time_picked(update, context, clock)


ASKS = {
    "budget": ask_budget, "dates": ask_dates, "flights": ask_flights, "frequency": ask_frequency,
    "window": ask_window, "sort": ask_sort, "limit": ask_limit, "day": ask_day, "time": ask_time,
}


def conversation() -> ConversationHandler:
    states = {
        MENU: [choice_step("edit:field", field_picked, "|".join(ASKS)), CallbackQueryHandler(done, pattern="^edit:done$")],
        BUDGET: [MessageHandler(TEXT, budget_typed),
                 choice_step("edit:bud", budget_picked, "|".join(map(str, [*BUDGET_OPTIONS, 0])))],
        DATES: dates_step("edit:date", DATES, dates_picked, ask_dates),
        FLIGHTS: [choice_step("edit:direct", flights_picked, "0|1")],
        FREQUENCY: [choice_step("edit:freq", frequency_picked, "|".join(map(str, FREQUENCIES)))],
        WINDOW: timeframe_step("edit:when", WINDOW, window_days_picked, window_dates_picked, ask_window),
        SORT: [choice_step("edit:sort", sort_picked, "discount|price|both")],
        LIMIT: [choice_step("edit:lim", limit_picked, "|".join(map(str, RESULT_LIMITS))), MessageHandler(TEXT, limit_typed)],
        DAY: [choice_step("edit:day", day_picked, "|".join(WEEKDAYS))],
        TIME: [choice_step("edit:time", time_picked, "|".join(TIME_OPTIONS)), MessageHandler(TEXT, time_typed)],
    }
    states = {state: [_current_message_only(h) for h in handlers] for state, handlers in states.items()}
    return wizard_conversation("edit", [
        CallbackQueryHandler(open_editor, pattern=r"^dash:edit:[td]:\d+$"),
        CallbackQueryHandler(open_budget, pattern=r"^dash:budget:[td]:\d+$"),
    ], states, back_to_menu)
