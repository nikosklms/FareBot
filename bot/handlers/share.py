"""Share links: a t.me link that lets another allowed user add the same tracker or digest.

The link's start parameter holds every setting, so nothing is stored and links survive restarts.
Telegram allows 64 characters from A-Z, a-z, 0-9, '_' and '-':
  tracker: t-ORIGIN-DEST-START-END-DIRECT-BUDGET-HOURS
  digest:  g-ORIGIN-REGION-WINDOW-SORT-BUDGET-WEEKDAY-TIME-RESULTS
Dates are YYYYMMDD (END is 0 for a single date), budgets are cents (0 = any), a digest WINDOW is
either days ahead or START_END, SORT is d/p/b and TIME is HHMM.
"""
import re
import urllib.parse
from datetime import date
from typing import Optional, Union

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.formatting import budget_text, eur, flight_type_label
from bot.handlers.dashboard import DIGEST, TRACKER, label_for, load_owned
from bot.handlers.digest import MAX_RESULTS, create_digest
from bot.handlers.track import FREQUENCIES, TrackerRejected, create_tracker_for_user, tracker_created_text
from bot.keyboards import button
from bot.services import get_services
from database.models import WEEKDAYS, Digest, Tracker
from services.airports_data import REGION_LABELS, region_display_name
from utils.date_parser import describe_window, window_problem

ADD, DISMISS = "sh:add:", "sh:no"
SORTS = {"discount": "d", "price": "p", "both": "b"}
CODE = re.compile(r"^[A-Z]{3}$")


def _compact(iso: Optional[str]) -> str:
    return iso.replace("-", "") if iso else "0"


def _iso(compact: str) -> str:
    return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8])).isoformat() if len(compact) == 8 else ""


def _cents(amount: Optional[float]) -> str:
    return str(round((amount or 0) * 100))


def share_payload(item: Union[Tracker, Digest]) -> str:
    if isinstance(item, Tracker):
        parts = ["t", item.origin_code, item.destination_code, _compact(item.departure_date),
                 _compact(item.departure_date_end), str(int(item.direct_only)), _cents(item.max_budget),
                 str(item.frequency_hours)]
    else:
        window = (str(item.days_ahead) if item.days_ahead is not None
                  else "_".join(_compact(d) for d in (item.departure_date, item.departure_date_end) if d))
        parts = ["g", item.origin_code, item.region, window, SORTS[item.sort_mode], _cents(item.max_budget),
                 str(WEEKDAYS.index(item.delivery_day)), item.delivery_time.replace(":", ""), str(item.max_results)]
    return "-".join(parts)


def parse_tracker(parts: list[str]) -> dict:
    origin, destination, start, end, direct, cents, hours = parts
    settings = {
        "origin": origin, "destination": destination, "start": _iso(start), "end": _iso(end) if end != "0" else None,
        "direct_only": direct == "1", "budget": int(cents) / 100, "hours": int(hours),
    }
    if not (CODE.match(origin) and CODE.match(destination) and settings["start"] and settings["budget"] > 0
            and settings["hours"] in FREQUENCIES and direct in ("0", "1")):
        raise ValueError(parts)
    if settings["end"] is not None and settings["end"] < settings["start"]:
        raise ValueError(parts)
    return settings


def parse_digest(parts: list[str]) -> dict:
    origin, region, window, sort, cents, weekday, hhmm, results = parts
    days, start, end = None, None, None
    if window.isdigit() and len(window) < 8:
        days = int(window)
    else:
        start, *rest = [_iso(d) for d in window.split("_")]
        end = rest[0] if rest else None
    settings = {
        "origin": origin, "region": region, "days": days, "start": start, "end": end,
        "sort": {code: mode for mode, code in SORTS.items()}[sort], "budget": int(cents) / 100 or None,
        "day": WEEKDAYS[int(weekday)], "time": f"{int(hhmm[:2]):02d}:{int(hhmm[2:]):02d}", "limit": int(results),
    }
    if not (CODE.match(origin) and region in REGION_LABELS and len(hhmm) == 4 and int(hhmm[:2]) < 24
            and int(hhmm[2:]) < 60 and 1 <= settings["limit"] <= MAX_RESULTS and (days or start)):
        raise ValueError(parts)
    return settings


def parse_payload(payload: str) -> Optional[tuple[str, dict]]:
    """('t' or 'g', settings) for a valid share payload, else None."""
    kind, *parts = payload.split("-")
    try:
        if kind == "t" and len(parts) == 7:
            return kind, parse_tracker(parts)
        if kind == "g" and len(parts) == 8:
            return kind, parse_digest(parts)
    except (ValueError, KeyError, IndexError):
        pass
    return None


def preview(kind: str, s: dict) -> str:
    if kind == "t":
        return "\n".join([
            "🔗 <b>Shared tracker</b>",
            "",
            f"📍 <b>Route</b>: {s['origin']} ✈️ {s['destination']}",
            f"📅 <b>Date</b>: {describe_window(s['start'], s['end'])}",
            f"⚙️ <b>Flights</b>: {flight_type_label(s['direct_only'])}",
            f"🎯 <b>Target budget</b>: {eur(s['budget'])}",
            f"🔄 <b>Checks</b>: every {s['hours']} hours",
        ])
    window = f"next {s['days']} days" if s["days"] else describe_window(s["start"], s["end"])
    return "\n".join([
        "🔗 <b>Shared weekly digest</b>",
        "",
        f"📍 <b>Route</b>: {s['origin']} ✈️ {region_display_name(s['region'])}",
        f"⏰ <b>Delivery</b>: every {s['day']} at {s['time']}",
        f"📅 <b>Departures</b>: {window}",
        f"🎯 <b>Budget</b>: {budget_text(s['budget'])}",
        f"📊 <b>Shows</b>: up to {s['limit']} deals",
    ])


def _dates_problem(kind: str, s: dict) -> Optional[str]:
    if kind == "g" and s["days"]:
        return None
    return window_problem(s["start"], s["end"])


async def open_shared(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> None:
    """/start <payload>: show what was shared and offer to add it."""
    parsed = parse_payload(payload)
    if not parsed:
        await update.message.reply_text("🔗 That share link is broken or incomplete. Ask for a new one.")
        return
    kind, settings = parsed
    problem = _dates_problem(kind, settings)
    if problem:
        await update.message.reply_text(f"{preview(kind, settings)}\n\n⚠️ Its dates have passed, so it can't be added.")
        return
    label = "✅ Add This Tracker" if kind == "t" else "✅ Add This Digest"
    buttons = InlineKeyboardMarkup([[button(label, ADD + payload), button("❌ No Thanks", DISMISS)]])
    await update.message.reply_text(f"{preview(kind, settings)}\n\nAdd it to your account?", reply_markup=buttons)


async def add_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.data == DISMISS:
        await query.answer()
        await query.edit_message_text("👌 Not added.")
        return
    parsed = parse_payload(query.data.removeprefix(ADD))
    problem = parsed and _dates_problem(*parsed)
    if not parsed or problem:
        await query.answer("This link can't be used anymore.", show_alert=True)
        return
    await query.answer()
    kind, s = parsed
    if kind == "g":
        await create_digest(update, context, s)
        return
    try:
        tracker = await create_tracker_for_user(context, query.from_user.id, s["origin"], s["destination"], s["start"],
                                                s["end"], s["budget"], s["hours"], s["direct_only"])
    except TrackerRejected as rejected:
        await query.edit_message_text(rejected.text, reply_markup=rejected.reply_markup)
        return
    await query.edit_message_text(tracker_created_text(tracker))


async def share_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The Share button on a /mytracks card: send a link and a button to forward it."""
    query = update.callback_query
    _, _, kind, raw_id = query.data.split(":")
    item = await load_owned(get_services(context), kind, int(raw_id), query.from_user.id)
    if not item:
        await query.answer("This item no longer exists.", show_alert=True)
        return
    await query.answer()
    link = f"https://t.me/{context.bot.username}?start={share_payload(item)}"
    what = (f"{item.origin_code} → {item.destination_code}" if kind == TRACKER
            else f"{item.origin_code} → {region_display_name(item.region)} deals")
    forward = "https://t.me/share/url?" + urllib.parse.urlencode({"url": link, "text": f"Track {what} with FareBot"})
    await query.message.reply_text(
        f"🔗 <b>Share {label_for(kind, item.id)}</b>\n\n"
        f"Anyone you send this link to can add the same {'tracker' if kind == TRACKER else 'digest'} with one tap. "
        f"They need to be on the bot's allowed list.\n\n{link}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 Send to a Friend", url=forward)]]),
    )


share_handlers = [
    CallbackQueryHandler(share_pressed, pattern=rf"^sh:link:[{TRACKER}{DIGEST}]:\d+$"),
    CallbackQueryHandler(add_pressed, pattern=rf"^({re.escape(ADD)}|{DISMISS}$)"),
]
