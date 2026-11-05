"""Admin /limits: how many trackers and digests people may have active, and how many days they may search,
for everyone at once or for one person.

Callback data: 'lim:home' (the overview), 'lim:who:<user id>' (one person's limits; EVERYONE for everyone's),
'lim:set:<user id>:<a|d>:<value>' (a for active, d for days) and 'lim:reset:<user id>' (back to everyone's).
"""
from typing import Optional

from telegram import CallbackQuery, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.auth import ADMIN_LIMITS, admin_id, describe_user, with_defaults
from bot.handlers.access import ADMIN_ONLY
from bot.keyboards import NOOP, back_button, button
from bot.services import get_services
from config import MAX_TRACKERS_PER_USER, get_allowed_users
from database.db import Database
from database.models import APPROVED, EVERYONE, Limits
from utils.date_parser import MAX_RANGE_DAYS

ACTIVE_OPTIONS = [1, 2, 3, 5, 8, 10, 15, MAX_TRACKERS_PER_USER]
DAY_OPTIONS = [30, 60, 90, 120, 180, 240, 300, MAX_RANGE_DAYS]
FIELDS = {"a": ("max_active", ACTIVE_OPTIONS), "d": ("max_range_days", DAY_OPTIONS)}
GONE = "This person doesn't have access anymore."
YOURS = (f"Your own limits are always the most: {ADMIN_LIMITS.max_active} active · "
         f"{ADMIN_LIMITS.max_range_days} days.")

View = tuple[str, InlineKeyboardMarkup]
People = dict[int, tuple[Optional[str], Optional[str]]]


async def _people(db: Database) -> People:
    """Everyone with access except the admin, as user ID -> (username, full name):
    ALLOWED_USERS first, then approved users."""
    known = {u.user_id: u for u in await db.list_users()}
    ids = [uid for uid in get_allowed_users() if uid != admin_id()]
    ids += [uid for uid, u in known.items() if u.status == APPROVED and uid not in ids]
    return {uid: (known[uid].username, known[uid].full_name) if uid in known else (None, None) for uid in ids}


def _label(uid: int, username: Optional[str], full_name: Optional[str]) -> str:
    name = full_name or username or f"ID {uid}"
    return name if len(name) <= 28 else name[:27] + "…"


def overview(people: People, stored: dict[int, Limits]) -> View:
    """stored: every row of the limits table (Database.get_limits with no IDs)."""
    everyone = with_defaults(Limits(), stored.get(EVERYONE, Limits()))
    lines = ["⚙️ <b>Limits</b>: active trackers + digests, and how many days ahead people can search", "",
             f"👥 <b>Everyone</b>: {everyone.max_active} active · {everyone.max_range_days} days",
             f"👑 <b>You</b>: {ADMIN_LIMITS.max_active} active · {ADMIN_LIMITS.max_range_days} days "
             "(the admin always has the most)",
             "", f"👤 <b>People</b> ({len(people)})"]
    for uid, (username, full_name) in people.items():
        own = stored.get(uid, Limits())
        limits = with_defaults(own, everyone)
        lines.append(f"• {describe_user(uid, username, full_name)}: "
                     f"{limits.max_active} active{' ✏️' if own.max_active else ''} · "
                     f"{limits.max_range_days} days{' ✏️' if own.max_range_days else ''}")
    if not people:
        lines.append("• nobody yet")
    lines += ["", "✏️ = their own limit. Tap Everyone, or someone to give them limits of their own. "
                  "Lowering a limit doesn't pause or shorten anything people already have."]
    rows = [[button("👥 Everyone", f"lim:who:{EVERYONE}")]]
    rows += [[button(f"👤 {_label(uid, *names)}", f"lim:who:{uid}")] for uid, names in people.items()]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def person_view(uid: int, people: People, stored: dict[int, Limits]) -> View:
    everyone = with_defaults(Limits(), stored.get(EVERYONE, Limits()))
    own = Limits() if uid == EVERYONE else stored.get(uid, Limits())
    current = with_defaults(own, everyone)
    title = ("👥 Everyone without limits of their own" if uid == EVERYONE
             else f"👤 {describe_user(uid, *people[uid])}")

    def source(value: Optional[int]) -> str:
        return "" if uid == EVERYONE else " (their own)" if value else " (everyone's)"

    def choices(key: str, chosen: int) -> list[list]:
        buttons = [button(f"✅ {n}" if n == chosen else str(n), f"lim:set:{uid}:{key}:{n}") for n in FIELDS[key][1]]
        return [buttons[:4], buttons[4:]]

    text = "\n".join([
        f"⚙️ <b>Limits</b> · {title}", "",
        f"🔔 <b>Active trackers + digests</b>: {current.max_active}{source(own.max_active)}",
        f"📅 <b>Days ahead / date range</b>: {current.max_range_days}{source(own.max_range_days)}",
        "", "Tap a number to change it.",
    ])
    rows = [[button("🔔 Active trackers + digests", NOOP)], *choices("a", current.max_active),
            [button("📅 Days ahead / date range", NOOP)], *choices("d", current.max_range_days)]
    if own.max_active or own.max_range_days:
        rows.append([button(f"↩️ Use Everyone's ({everyone.max_active} active · {everyone.max_range_days} days)",
                            f"lim:reset:{uid}")])
    rows.append([back_button("lim:home")])
    return text, InlineKeyboardMarkup(rows)


async def _show(query: CallbackQuery, view: View) -> None:
    text, markup = view
    await query.edit_message_text(text, reply_markup=markup)


async def limits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != admin_id():
        await update.message.reply_text(ADMIN_ONLY)
        return
    db = get_services(context).db
    text, markup = overview(await _people(db), await db.get_limits())
    await update.message.reply_text(text, reply_markup=markup)


async def limits_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != admin_id():
        await query.answer(ADMIN_ONLY, show_alert=True)
        return
    db = get_services(context).db
    people, stored = await _people(db), await db.get_limits()
    action, *rest = query.data.split(":")[1:]
    if action == "home":
        await query.answer()
        await _show(query, overview(people, stored))
        return

    uid = int(rest[0])
    if uid == admin_id():  # only a modified Telegram app sends the admin's own ID
        await query.answer(YOURS, show_alert=True)
        return
    if uid != EVERYONE and uid not in people:
        await query.answer(GONE, show_alert=True)
        await _show(query, overview(people, stored))
        return

    if action == "set":
        field, options = FIELDS[rest[1]]
        value = int(rest[2])
        if value not in options:  # only a modified Telegram app sends other values
            await query.answer("Pick one of the numbers shown.", show_alert=True)
            return
        own = stored.get(uid, Limits())
        # Everyone's screen shows the config default when nothing is stored; a person's shows whose value it is.
        shown = getattr(with_defaults(own, Limits()) if uid == EVERYONE else own, field)
        if shown == value:
            await query.answer(f"It's already {value}.")
            return
        await db.set_limit(uid, field, value)
        await query.answer("✅ Saved")
        stored = await db.get_limits()
    elif action == "reset":
        await db.clear_limits(uid)
        await query.answer("✅ Back to everyone's limits")
        stored = await db.get_limits()
    else:
        await query.answer()
    await _show(query, person_view(uid, people, stored))


limits_handlers = [
    CommandHandler("limits", limits_command),
    CallbackQueryHandler(limits_pressed, pattern=r"^lim:(home|who:\d+|set:\d+:[ad]:\d+|reset:\d+)$"),
]
