"""Admin /limits: how many trackers and digests people may have active, and how many days they may search,
for everyone at once or for one person, by button or typed. A person's screen also opens their trackers and
digests, which the admin can pause, resume, edit or delete like their own (see dashboard.py).

Commands: /limits (the overview), /limits <ID|everyone> (one screen), /limits <ID|everyone> active <n> days <n>
(either or both) and /limits <ID|everyone> reset. IDs are shown in /users.

Callback data: 'lim:home' (the overview), 'lim:who:<user id>' (one person's limits; EVERYONE for everyone's),
'lim:set:<user id>:<a|d>:<value>' (a for active, d for days), 'lim:type:<user id>:<a|d>' (type a value),
'lim:reset:<user id>' (back to everyone's) and 'lim:items:<user id>' (their trackers and digests).
"""
from dataclasses import dataclass
from html import escape
from typing import Optional

from telegram import CallbackQuery, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler

from bot.auth import ADMIN_LIMITS, admin_id, button_name, describe_user, parse_user_id, with_defaults
from bot.handlers.access import ADMIN_ONLY
from bot.handlers.dashboard import send_someones_items
from bot.keyboards import NOOP, back_button, button, markup
from bot.services import get_services
from bot.wizard import ACTIVE_WIZARD_KEY, TEXT, Context, draft, respond, start_draft, wizard_conversation
from config import MAX_TRACKERS_PER_USER, get_allowed_users
from database.db import Database
from database.models import APPROVED, EVERYONE, Limits
from utils.date_parser import MAX_RANGE_DAYS


@dataclass(frozen=True)
class Field:
    key: str  # in callback data
    column: str  # in the limits table
    options: list[int]  # the buttons; the last is the highest allowed
    lowest: int
    asks: str

    @property
    def highest(self) -> int:
        return self.options[-1]

    def allows(self, value: int) -> bool:
        return self.lowest <= value <= self.highest


# The admin's own limits are the highest. Days start at 30, the default for /explore and /digest.
FIELDS = {f.key: f for f in (
    Field("a", "max_active", [1, 2, 3, 5, 8, 10, 15, MAX_TRACKERS_PER_USER], 1,
          "how many trackers and digests {who} can have active"),
    Field("d", "max_range_days", [30, 60, 90, 120, 180, 240, 300, MAX_RANGE_DAYS], 30,
          "how many days ahead {who} can search"),
)}
GONE = "This person doesn't have access anymore."
USAGE = ("⌨️ <b>Shortcuts</b> (copy IDs from /users): <code>/limits ID</code> · "
         "<code>/limits ID active 5 days 90</code> · <code>/limits everyone days 120</code> · "
         "<code>/limits ID reset</code>")
NAMES = {"active": "a", "days": "d"}
YOURS = (f"Your own limits are always the most: {ADMIN_LIMITS.max_active} active · "
         f"{ADMIN_LIMITS.max_range_days} days.")
TYPING = 0
DRAFT = "limits"
LISTED = 30  # people shown in the overview; Telegram messages hold 4096 characters

View = tuple[str, InlineKeyboardMarkup]
People = dict[int, tuple[Optional[str], Optional[str]]]


async def _people(db: Database) -> People:
    """Everyone with access except the admin, as user ID -> (username, full name):
    ALLOWED_USERS first, then approved users."""
    known = {u.user_id: u for u in await db.list_users()}
    ids = [uid for uid in get_allowed_users() if uid != admin_id()]
    ids += [uid for uid, u in known.items() if u.status == APPROVED and uid not in ids]
    return {uid: (known[uid].username, known[uid].full_name) if uid in known else (None, None) for uid in ids}


def _problem(uid: int, people: People) -> Optional[str]:
    """Why the admin can't change this user ID's limits, if they can't."""
    if uid == admin_id():  # only a modified Telegram app sends the admin's own ID
        return YOURS
    return GONE if uid != EVERYONE and uid not in people else None


async def overview(db: Database, people: People) -> View:
    stored = await db.get_limits()
    everyone = with_defaults(Limits(), stored.get(EVERYONE, Limits()))
    lines = ["⚙️ <b>Limits</b>: active trackers + digests, and how many days ahead people can search", "",
             f"👥 <b>Everyone</b>: {everyone.max_active} active · {everyone.max_range_days} days",
             f"👑 <b>You</b>: {ADMIN_LIMITS.max_active} active · {ADMIN_LIMITS.max_range_days} days "
             "(the admin always has the most)",
             "", f"👤 <b>People</b> ({len(people)})"]
    listed = list(people.items())[:LISTED]
    for uid, (username, full_name) in listed:
        own = stored.get(uid, Limits())
        limits = with_defaults(own, everyone)
        lines.append(f"• {describe_user(uid, username, full_name)}: "
                     f"{limits.max_active} active{' ✏️' if own.max_active else ''} · "
                     f"{limits.max_range_days} days{' ✏️' if own.max_range_days else ''}")
    if not people:
        lines.append("• nobody yet")
    elif len(people) > LISTED:
        lines.append(f"• …and {len(people) - LISTED} more: open them with <code>/limits ID</code>")
    lines += ["", "✏️ = their own limit. Tap Everyone, or someone to give them limits of their own or to see "
                  "their trackers and digests. Lowering a limit doesn't pause or shorten anything people already have.",
              "", USAGE]
    rows = [[button("👥 Everyone", f"lim:who:{EVERYONE}")]]
    rows += [[button(f"👤 {button_name(uid, *names)}", f"lim:who:{uid}")] for uid, names in listed]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def person_view(db: Database, uid: int, people: People) -> View:
    stored = await db.get_limits()
    everyone = with_defaults(Limits(), stored.get(EVERYONE, Limits()))
    own = Limits() if uid == EVERYONE else stored.get(uid, Limits())
    current = with_defaults(own, everyone)

    def source(value: Optional[int]) -> str:
        return "" if uid == EVERYONE else " (their own)" if value else " (everyone's)"

    def choices(field: Field, chosen: int) -> list[list]:
        buttons = [button(f"✅ {n}" if n == chosen else str(n), f"lim:set:{uid}:{field.key}:{n}")
                   for n in field.options]
        return [buttons[:4], buttons[4:]]

    title = ("👥 Everyone without limits of their own" if uid == EVERYONE
             else f"👤 {describe_user(uid, *people[uid])}")
    lines = [f"⚙️ <b>Limits</b> · {title}", "",
             f"🔔 <b>Active trackers + digests</b>: {current.max_active}{source(own.max_active)}",
             f"📅 <b>Days ahead / date range</b>: {current.max_range_days}{source(own.max_range_days)}"]
    if uid != EVERYONE:
        lines.append(f"📊 <b>Active right now</b>: {await db.count_active(uid)}")
    lines += ["", "Tap a number, or type one."]
    rows = [[button("🔔 Active trackers + digests", NOOP)], *choices(FIELDS["a"], current.max_active),
            [button("📅 Days ahead / date range", NOOP)], *choices(FIELDS["d"], current.max_range_days),
            [button("⌨️ Type Active", f"lim:type:{uid}:a"), button("⌨️ Type Days", f"lim:type:{uid}:d")]]
    if own.max_active or own.max_range_days:
        rows.append([button(f"↩️ Use Everyone's ({everyone.max_active} active · {everyone.max_range_days} days)",
                            f"lim:reset:{uid}")])
    if uid != EVERYONE:
        rows.append([button("📋 Their Trackers & Digests", f"lim:items:{uid}")])
    rows.append([back_button("lim:home")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _save(db: Database, uid: int, field: Field, value: int) -> bool:
    """Store a new value; False if it's already the one that applies (the ✅ on the screen), so picking
    everyone's value for someone doesn't quietly stop them following everyone's."""
    stored = await db.get_limits(uid, EVERYONE)
    own = Limits() if uid == EVERYONE else stored.get(uid, Limits())
    if getattr(with_defaults(own, stored.get(EVERYONE, Limits())), field.column) == value:
        return False
    await db.set_limit(uid, field.column, value)
    return True


async def _show(query: CallbackQuery, view: View) -> None:
    text, markup_ = view
    await query.edit_message_text(text, reply_markup=markup_)


def _parse_changes(words: list[str]) -> Optional[dict[str, int]]:
    """'active 5 days 90' (either or both, any order) -> {field key: value}; None if it can't be read."""
    if not words or len(words) % 2 or len(words) > 4:
        return None
    changes = {}
    for name, value in zip(words[::2], words[1::2], strict=True):
        key = NAMES.get(name)
        if not key or key in changes or not value.isdecimal():
            return None
        changes[key] = int(value)
    return changes


async def limits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != admin_id():
        await update.message.reply_text(ADMIN_ONLY)
        return
    db = get_services(context).db
    people = await _people(db)
    args = [arg.lower() for arg in context.args or []]
    if not args:
        text, markup_ = await overview(db, people)
        await update.message.reply_text(text, reply_markup=markup_)
        return

    target = EVERYONE if args[0] == "everyone" else parse_user_id(args[0])
    if target is None:
        await update.message.reply_text(f"❌ Start with a person's ID or <code>everyone</code>.\n\n{USAGE}")
        return
    problem = _problem(target, people)
    if problem:
        await update.message.reply_text(f"❌ {problem}" if problem == YOURS else
                                        f"❌ Nobody with ID <code>{target}</code> has access. IDs are in /users.")
        return

    note = ""
    if args[1:] == ["reset"]:
        await db.clear_limits(target)
        note = "✅ <b>Back to the defaults.</b>" if target == EVERYONE else "✅ <b>Back to everyone's limits.</b>"
    elif args[1:]:
        changes = _parse_changes(args[1:])
        if changes is None:
            await update.message.reply_text(f"❌ I couldn't read that.\n\n{USAGE}")
            return
        wrong = [name for name, key in NAMES.items() if key in changes and not FIELDS[key].allows(changes[key])]
        if wrong:
            await update.message.reply_text("❌ " + " ".join(
                f"<code>{name}</code> must be from {FIELDS[NAMES[name]].lowest} to {FIELDS[NAMES[name]].highest}."
                for name in wrong))
            return
        saved = [await _save(db, target, FIELDS[key], value) for key, value in changes.items()]
        note = "✅ <b>Saved.</b>" if any(saved) else "ℹ️ Nothing changed: those limits already apply."
    text, markup_ = await person_view(db, target, people)
    await update.message.reply_text(f"{note}\n\n{text}" if note else text, reply_markup=markup_)


async def limits_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != admin_id():
        await query.answer(ADMIN_ONLY, show_alert=True)
        return
    if context.user_data.get(ACTIVE_WIZARD_KEY) == DRAFT:
        # Typing a number was left open; it was for the screen before this one, so stop it.
        context.user_data.pop(ACTIVE_WIZARD_KEY)
    db = get_services(context).db
    people = await _people(db)
    action, *rest = query.data.split(":")[1:]
    if action == "home":
        await query.answer()
        await _show(query, await overview(db, people))
        return

    uid = int(rest[0])
    problem = _problem(uid, people)
    if problem:
        await query.answer(problem, show_alert=True)
        if problem == GONE:
            await _show(query, await overview(db, people))
        return

    if action == "items":
        await query.answer()
        await send_someones_items(context, query.message.chat_id, uid)
        return
    if action == "set":
        field, value = FIELDS[rest[1]], int(rest[2])
        if not field.allows(value):  # only a modified Telegram app sends other values
            await query.answer(f"Pick a number from {field.lowest} to {field.highest}.", show_alert=True)
            return
        if not await _save(db, uid, field, value):
            await query.answer(f"It's already {value}.")
            return
        await query.answer("✅ Saved")
    elif action == "reset":
        await db.clear_limits(uid)
        await query.answer("✅ Back to everyone's limits")
    else:
        await query.answer()
    await _show(query, await person_view(db, uid, people))


# ----------------------------------------------------------------------
# Typing a number
# ----------------------------------------------------------------------

async def ask_number(update: Update, context: Context) -> int:
    query = update.callback_query
    if query.from_user.id != admin_id():
        await query.answer(ADMIN_ONLY, show_alert=True)
        return ConversationHandler.END
    _, _, raw_uid, key = query.data.split(":")
    uid, field = int(raw_uid), FIELDS[key]
    people = await _people(get_services(context).db)
    problem = _problem(uid, people)
    if problem:
        await query.answer(problem, show_alert=True)
        return ConversationHandler.END
    await query.answer()
    d = start_draft(context, DRAFT)
    d["uid"], d["key"] = uid, key
    who = "everyone" if uid == EVERYONE else escape(button_name(uid, *people[uid]))
    await respond(update, f"⌨️ Type {field.asks.format(who=who)}, from {field.lowest} to {field.highest}:",
                  markup(back=True))
    return TYPING


async def number_typed(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    uid, field = d["uid"], FIELDS[d["key"]]
    db = get_services(context).db
    people = await _people(db)
    problem = _problem(uid, people)
    if problem:
        await update.message.reply_text(problem)
        return ConversationHandler.END
    text = update.message.text.strip()
    if not text.isdecimal() or not field.allows(int(text)):
        await update.message.reply_text(f"❌ Type a whole number from {field.lowest} to {field.highest}.",
                                        reply_markup=markup(back=True))
        return TYPING
    note = "✅ <b>Saved.</b>" if await _save(db, uid, field, int(text)) else f"It's already {int(text)}."
    text, markup_ = await person_view(db, uid, people)
    await update.message.reply_text(f"{note}\n\n{text}", reply_markup=markup_)
    return ConversationHandler.END


async def back_to_person(update: Update, context: Context) -> int:
    await update.callback_query.answer()
    db = get_services(context).db
    people = await _people(db)
    uid = draft(context, DRAFT)["uid"]
    view = await overview(db, people) if _problem(uid, people) else await person_view(db, uid, people)
    await respond(update, *view)
    return ConversationHandler.END


def conversation() -> ConversationHandler:
    return wizard_conversation(DRAFT, CallbackQueryHandler(ask_number, pattern=r"^lim:type:\d+:[ad]$"),
                               {TYPING: [MessageHandler(TEXT, number_typed)]}, back_to_person)


limits_handlers = [
    CommandHandler("limits", limits_command),
    CallbackQueryHandler(limits_pressed, pattern=r"^lim:(home|who:\d+|set:\d+:[ad]:\d+|reset:\d+|items:\d+)$"),
]
