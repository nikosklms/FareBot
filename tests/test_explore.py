from providers.base import FlightOffer
from tests.fakes import future

PRICES = {"FCO": (40.0, 90.0, 110.0), "CDG": (100.0, 190.0, 210.0), "SOF": (20.0, None, None)}


def regional_offers(origin, destination, day):
    if destination not in PRICES:
        return []
    price, low, high = PRICES[destination]
    return [FlightOffer(origin, destination, day, price=price, airline="Air", typical_min=low, typical_max=high)]


async def test_full_wizard(bot, provider):
    provider.offers = regional_offers
    await bot.send("/explore")
    assert "Step 1/5" in bot.telegram.last_text
    await bot.press("exp:org:ATH")
    assert "Step 2/5" in bot.telegram.last_text
    await bot.press("exp:reg:europe")
    assert "Europe" in bot.telegram.last_text
    await bot.press("exp:sort:discount")
    await bot.press("exp:when:days:7")
    assert f"{future(1)} ➔ {future(7)}" in bot.telegram.last_text
    await bot.press("exp:lim:2")
    assert bot.telegram.button_data("Stop") == "task:stop"
    await bot.finish_background_task()

    report = bot.telegram.last_text
    assert "BIGGEST DISCOUNTS" in report and "CHEAPEST FLIGHTS" not in report
    assert report.index("ATH ✈️ FCO") < report.index("ATH ✈️ CDG")
    assert "ATH ✈️ SOF" not in report
    assert {d for _, d, day, _ in provider.queries if day == future(7)} >= {"FCO", "CDG"}
    assert bot.telegram.last_buttons() == [("🔔 Track a deal", "deals:show")]
    results_message = bot.telegram.last_message_id
    await bot.press("deals:show", message_id=results_message)
    assert bot.telegram.button_data("Track #1") == f"trk:add:ATH:FCO:{future(1)}::36.00:0"


async def test_typed_timeframe_and_limit(bot, provider):
    provider.offers = regional_offers
    await bot.send("/explore")
    await bot.press("exp:org:SKG")
    await bot.press("exp:reg:europe")
    await bot.press("exp:sort:price")
    await bot.send("400")
    assert "between 1 and 330" in bot.telegram.last_text
    await bot.send("3")
    await bot.send("50")
    assert "from 1 to 20" in bot.telegram.last_text
    await bot.send("1")
    await bot.finish_background_task()
    assert "CHEAPEST FLIGHTS" in bot.telegram.last_text
    assert bot.telegram.last_text.count("SKG ✈️") == 1 and "SKG ✈️ SOF" in bot.telegram.last_text


async def test_calendar_dates(bot, provider):
    await bot.send("/explore")
    await bot.press("exp:org:ATH")
    await bot.press("exp:reg:asia")
    await bot.press("exp:sort:both")
    await bot.press("exp:when:cal:open")
    await bot.press("exp:when:cal:mode:single")
    await bot.press(f"exp:when:cal:day:{future(20)}")
    assert f"<b>Departures</b>: {future(20)}\n" in bot.telegram.last_text


async def test_shortcut_days_budget_and_limit(bot, provider):
    provider.offers = regional_offers
    await bot.send("/explore ATH europe 3 50 1")
    await bot.finish_background_task()

    assert {day for _, _, day, _ in provider.queries} == {future(1), future(2), future(3)}
    report = bot.telegram.last_text
    assert "BIGGEST DISCOUNTS" in report and "CHEAPEST FLIGHTS" in report
    assert "CDG" not in report
    assert report.count("ATH ✈️") == 2


async def test_shortcut_rejects_bad_input(bot):
    await bot.send("/explore ATH moon")
    assert "Usage" in bot.telegram.last_text
    await bot.send("/explore ATH europe soon")
    assert "Usage" in bot.telegram.last_text


async def test_no_deals(bot):
    await bot.send("/explore ATH oceania 2 30")
    await bot.finish_background_task()
    assert "No deals found under €30.00" in bot.telegram.last_text


async def test_track_buttons_expand_and_collapse(bot, provider):
    provider.offers = regional_offers
    await bot.send("/explore ATH europe 1")
    await bot.finish_background_task()
    results_message = bot.telegram.last_message_id

    await bot.press("deals:show", message_id=results_message)
    labels = [label for label, _ in bot.telegram.last_buttons()]
    assert labels[0].startswith("🔔 Track #1") and labels[-1] == "🔼 Hide"
    assert len(labels) == 7  # 3 deals in each of the two lists, plus Hide

    await bot.press("deals:hide", message_id=results_message)
    assert bot.telegram.last_buttons() == [("🔔 Track a deal", "deals:show")]


async def test_old_results_explain_instead_of_failing(bot):
    await bot.press("deals:show", message_id=4242)
    assert "too old" in bot.telegram.alerts[-1]
