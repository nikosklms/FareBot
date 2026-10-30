"""Track buttons under deal lists (/explore results and weekly digests).

A result shows a single button; tapping it reveals one Track button per deal and a Hide
button. The per-deal buttons are kept in user_data for the most recent results.
"""
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.formatting import numbered_deals
from bot.keyboards import button, track_button_data
from services.explore_engine import DealSection

SHOW_DEALS, HIDE_DEALS = "deals:show", "deals:hide"
DEAL_BUTTONS_KEY = "deal_buttons"
REMEMBERED_RESULTS = 10
TRACK_DISCOUNT = 0.90  # tracking a deal targets 10% below its price
COLLAPSED = InlineKeyboardMarkup([[button("🔔 Track a deal", SHOW_DEALS)]])


def deal_buttons(sections: list[DealSection]) -> list[tuple[str, str]]:
    """(label, callback data) of each deal's Track button."""
    buttons = []
    for index, deal in numbered_deals(sections):
        budget = round(deal.price * TRACK_DISCOUNT, 2)
        buttons.append((f"🔔 Track #{index}: {deal.destination} (alert under €{budget:.0f})",
                        track_button_data(deal.origin, deal.destination, deal.departure_date, None, budget)))
    return buttons


def remember_deal_buttons(user_data: dict, message_id: int, sections: list[DealSection]) -> None:
    saved = user_data.setdefault(DEAL_BUTTONS_KEY, {})
    saved[message_id] = deal_buttons(sections)
    while len(saved) > REMEMBERED_RESULTS:
        saved.pop(next(iter(saved)))


async def toggle_deal_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    buttons = context.user_data.get(DEAL_BUTTONS_KEY, {}).get(query.message.message_id)
    if buttons is None:
        await query.answer("These results are too old to track from. Use /track to add a route.", show_alert=True)
        return
    await query.answer()
    if query.data == SHOW_DEALS:
        rows = [[button(label, data)] for label, data in buttons] + [[button("🔼 Hide", HIDE_DEALS)]]
        await query.edit_message_reply_markup(InlineKeyboardMarkup(rows))
    else:
        await query.edit_message_reply_markup(COLLAPSED)


toggle_deals_handler = CallbackQueryHandler(toggle_deal_buttons, pattern=f"^({SHOW_DEALS}|{HIDE_DEALS})$")
