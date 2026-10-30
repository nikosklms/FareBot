"""HTML message rendering. Every line is self-contained so messages can be split on newlines."""
import math
from datetime import date, datetime, timedelta
from html import escape
from typing import Optional

from database.models import ACTIVE, PAUSED, Digest, Tracker
from providers.base import FlightOffer
from providers.fast_flights import build_google_flights_url
from services.airports_data import region_display_name
from services.explore_engine import Deal, DealSection, baseline_price
from utils.date_parser import describe_window

MAX_MESSAGE_LENGTH = 4000
NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
STATUS_ICONS = {ACTIVE: "🟢", PAUSED: "⏸️"}
SECTION_TITLES = {
    "discount": "💥 <b>BIGGEST DISCOUNTS</b>",
    "price": "💶 <b>CHEAPEST FLIGHTS</b>",
}


def bold(text: object) -> str:
    return f"<b>{escape(str(text))}</b>"


def link(text: str, url: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{text}</a>'


def eur(amount: float) -> str:
    return f"€{amount:.2f}"


def flight_type_label(direct_only: bool) -> str:
    return "Direct flights only ✈️" if direct_only else "Any flights (direct and with stops) 🔄"


def discount_badge(price: float, baseline: Optional[float], show_discount: bool = True) -> str:
    """'(💥 28% OFF · usually ~€104.00)', relative to Google's typical price."""
    if not baseline:
        return ""
    average = f"usually ~{eur(baseline)}"
    if show_discount:
        pct = round((baseline - price) / baseline * 100)
        if pct > 0:
            return f" (💥 <b>{pct}% OFF</b> · {average})"
        if pct < 0:
            return f" (📈 <b>{-pct}% above usual</b> · {average})"
    return f" ({average})"


def offer_line(offer: FlightOffer, index: int, show_date: bool, direct_only: bool = False) -> str:
    url = offer.booking_url or build_google_flights_url(offer.origin, offer.destination, offer.departure_date,
                                                       direct_only=direct_only)
    baseline = baseline_price(offer.typical_min, offer.typical_max)
    stops = "Direct ✈️" if offer.is_direct else "1+ Stops 🔄"
    parts = [
        NUMBER_EMOJIS[index] if index < len(NUMBER_EMOJIS) else f"{index + 1}.",
        f" {link(bold(eur(offer.price)), url)}",
        discount_badge(offer.price, baseline),
        f" ({offer.departure_date})" if show_date else "",
        f" — {escape(offer.airline or 'Various')} ({stops})",
    ]
    if offer.departure_time and offer.arrival_time:
        next_day = f" (+{offer.day_offset})" if offer.day_offset > 0 else ""
        parts.append(f" | 🕒 {offer.departure_time} ➔ {offer.arrival_time}{next_day}")
    return "".join(parts)


def offers_block(offers: list[FlightOffer], show_date: bool, direct_only: bool = False) -> str:
    return "\n".join(offer_line(o, i, show_date, direct_only) for i, o in enumerate(offers))


def deal_entry(deal: Deal, index: int, show_discount: bool) -> str:
    url = build_google_flights_url(deal.origin, deal.destination, deal.departure_date)
    stops = "🟢 Direct" if deal.is_direct else "🟡 Connecting"
    return (
        f"{index}. <b>{deal.origin} ✈️ {deal.destination}</b> ({escape(deal.destination_name)})\n"
        f"💶 {link(bold(eur(deal.price)), url)}{discount_badge(deal.price, deal.baseline_price, show_discount)}"
        f" | {stops} | 📅 {deal.departure_date} ({escape(deal.airline)})"
    )


def numbered_deals(sections: list[DealSection]) -> list[tuple[int, Deal]]:
    """Deals across all sections with the running number shown next to each."""
    numbered = []
    for section in sections:
        for deal in section.deals:
            numbered.append((len(numbered) + 1, deal))
    return numbered


def deal_report(title: str, sections: list[DealSection]) -> str:
    lines = [title]
    numbers = iter(numbered_deals(sections))
    for section in sections:
        lines.append("")
        lines.append(SECTION_TITLES[section.sort_mode])
        for _deal in section.deals:
            index, deal = next(numbers)
            lines.append(deal_entry(deal, index, show_discount=section.sort_mode == "discount"))
            lines.append("")
    return "\n".join(lines).rstrip()


def short_date(iso_date: str) -> str:
    """'2026-10-31' -> '31 Oct'; the year is added when it isn't the current one."""
    day = date.fromisoformat(iso_date)
    return f"{day.day} {day:%b}" + (f" {day.year}" if day.year != date.today().year else "")


def short_window(start: str, end: Optional[str]) -> str:
    return f"{short_date(start)} ➔ {short_date(end)}" if end else short_date(start)


def countdown(seconds: float) -> str:
    """Fixed-format time: 0:07, 12:30, 1:05:00."""
    hours, rest = divmod(max(0, math.ceil(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def progress_bar(done: int, total: int, width: int = 10) -> str:
    filled = done * width // total if total else 0
    return "🟩" * filled + "⬜" * (width - filled)


def progress_text(title: str, details: str, done: int, total: int, seconds_left: float) -> str:
    """Short lines that fit a phone screen; only the bar and the times change between updates."""
    finish = (datetime.now().astimezone() + timedelta(seconds=seconds_left)).strftime("%H:%M")
    percent = done * 100 // total if total else 0
    return (f"{title}\n📅 {details}\n\n"
            f"{progress_bar(done, total)} {percent}%\n"
            f"⏱️ <b>{countdown(seconds_left)}</b> left · done around <b>{finish}</b>")


def query_scope(airports: int, days: int) -> str:
    if airports > 1 and days > 1:
        return f"{airports} airports × {days} days"
    if airports > 1:
        return f"{airports} airports"
    return f"{days} days" if days > 1 else ""


def split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split on line boundaries into chunks Telegram accepts."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split("\n"):
        if current and size + len(line) + 1 > limit:
            chunks.append("\n".join(current).strip("\n"))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current).strip("\n"))
    return [c for c in chunks if c]


def tracker_card(tracker: Tracker) -> str:
    icon = STATUS_ICONS.get(tracker.status, "🔴")
    last_price = eur(tracker.last_price_found) if tracker.last_price_found else "not checked yet"
    return "\n".join([
        f"{icon} <b>Tracker #{tracker.id}</b>",
        f"📍 <b>Route</b>: {tracker.origin_code} ✈️ {tracker.destination_code}",
        f"📅 <b>Date</b>: {describe_window(tracker.departure_date, tracker.departure_date_end)}",
        f"⚙️ <b>Flights</b>: {flight_type_label(tracker.direct_only)}",
        f"🎯 <b>Target budget</b>: {eur(tracker.max_budget)}",
        f"🔄 <b>Checks</b>: every {tracker.frequency_hours} hours",
        f"💶 <b>Last price</b>: {last_price}",
        f"📊 <b>Status</b>: {tracker.status}",
    ])


def digest_window_text(digest: Digest) -> str:
    if digest.days_ahead is not None:
        return f"next {digest.days_ahead} days"
    return describe_window(digest.departure_date, digest.departure_date_end)


def budget_text(max_budget: Optional[float]) -> str:
    return eur(max_budget) if max_budget else "Any budget"


def digest_card(digest: Digest) -> str:
    icon = STATUS_ICONS.get(digest.status, "🔴")
    sort_label = {"discount": "biggest discounts", "price": "cheapest", "both": "discounts + cheapest"}
    return "\n".join([
        f"{icon} 🗞️ <b>Weekly Digest #{digest.id}</b>",
        f"📍 <b>Route</b>: {digest.origin_code} ✈️ {region_display_name(digest.region)}",
        f"⏰ <b>Delivery</b>: every {digest.delivery_day} at {digest.delivery_time}",
        f"📅 <b>Departures</b>: {digest_window_text(digest)}",
        f"🎯 <b>Budget</b>: {budget_text(digest.max_budget)}",
        f"📊 <b>Shows</b>: up to {digest.max_results} deals ({sort_label.get(digest.sort_mode, digest.sort_mode)})",
        f"📊 <b>Status</b>: {digest.status}",
    ])

