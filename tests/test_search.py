import asyncio

from providers.base import FlightOffer
from tests.fakes import future


def priced(price_for_day=None, airline="Aegean", is_direct=True):
    def offers(origin, destination, day):
        price = price_for_day(day) if price_for_day else 99.0
        return [FlightOffer(origin, destination, day, price=price, airline=airline, is_direct=is_direct,
                            booking_url="https://flights.example/best")]
    return offers


async def start_to_dates(bot):
    await bot.send("/search")
    await bot.send("Athens")
    await bot.press(bot.telegram.button_data("ATH"))
    await bot.send("london")
    await bot.press(bot.telegram.button_data("LON -"))


async def test_full_wizard_single_date(bot, provider):
    provider.offers = priced()
    await bot.send("/search")
    assert "Step 1/4" in bot.telegram.last_text
    await bot.send("Athens")
    assert "Which airport" in bot.telegram.last_text
    await bot.press(bot.telegram.button_data("ATH"))
    assert "Step 2/4" in bot.telegram.last_text
    await bot.send("LON")
    await bot.press("src:dst:LON")
    assert "Step 3/4" in bot.telegram.last_text
    await bot.send(future(10))
    assert "Step 4/4" in bot.telegram.last_text
    await bot.press("src:direct:1")
    await bot.finish_background_task()

    assert provider.queries == [("ATH", "LON", future(10), True)]
    assert "<b>€99.00</b>" in bot.telegram.last_text
    assert bot.telegram.button_data("View Best Offer") == "https://flights.example/best"
    assert bot.telegram.button_data("Track This Route") == f"trk:add:ATH:LON:{future(10)}::99.00:1"


async def test_range_search_shows_dates_and_tracks_whole_range(bot, provider):
    provider.offers = priced(lambda day: 50.0 if day == future(11) else 80.0)
    await start_to_dates(bot)
    await bot.send(f"{future(10)}..{future(12)}")
    await bot.press("src:direct:0")
    await bot.finish_background_task()

    assert len(provider.queries) == 3
    assert any("⬜" * 10 + " 0%" in text and "· 3 days" in text for text in bot.telegram.texts)
    assert f"€50.00</b></a> ({future(11)})" in bot.telegram.last_text
    assert bot.telegram.button_data("Track") == f"trk:add:ATH:LON:{future(10)}:{future(12)}:50.00:0"


async def test_preset_dates(bot, provider):
    await start_to_dates(bot)
    await bot.press("src:date:preset:next_7_days")
    assert f"{future(1)} ➔ {future(7)}" in bot.telegram.last_text


async def test_calendar_range_selection(bot):
    await start_to_dates(bot)
    await bot.press("src:date:cal:open")
    assert "first day of the range" in bot.telegram.last_text
    await bot.press(f"src:date:cal:nav:{future(40)[:7]}")
    assert bot.telegram.calls[-1][0] == "editMessageReplyMarkup"
    await bot.press(f"src:date:cal:day:{future(12)}")
    assert "Now pick the last day" in bot.telegram.last_text
    assert ("🚩" + str(int(future(12)[-2:])), f"src:date:cal:day:{future(12)}") in bot.telegram.last_buttons()
    await bot.press(f"src:date:cal:day:{future(15)}")
    assert f"{future(12)} ➔ {future(15)}" in bot.telegram.last_text
    assert "Step 4/4" in bot.telegram.last_text


async def test_calendar_single_mode(bot):
    await start_to_dates(bot)
    await bot.press("src:date:cal:open")
    await bot.press("src:date:cal:mode:single")
    await bot.press(f"src:date:cal:day:{future(20)}")
    assert f"<b>Date</b>: {future(20)}\n" in bot.telegram.last_text


async def test_rejects_bad_and_past_dates(bot):
    await start_to_dates(bot)
    await bot.send("next friday")
    assert "couldn't read that date" in bot.telegram.last_text
    await bot.send("2020-01-01")
    assert "in the past" in bot.telegram.last_text


async def test_unknown_place(bot, monkeypatch):
    monkeypatch.setattr(bot.services.resolver, "resolve", lambda text: [])
    await bot.send("/search")
    await bot.send("Atlantis")
    assert "don't know that place" in bot.telegram.last_text
    await bot.send(f"/search Atlantis LON {future(5)}")
    assert "I don't know 'Atlantis'" in bot.telegram.last_text


async def test_no_results(bot):
    await bot.send(f"/search ATH LON {future(10)}")
    await bot.finish_background_task()
    assert "No flights found" in bot.telegram.last_text


async def test_shortcut_runs_search_and_validates(bot, provider):
    provider.offers = priced()
    await bot.send(f"/search ATH LON {future(10)} direct")
    await bot.finish_background_task()
    assert provider.queries == [("ATH", "LON", future(10), True)]

    await bot.send("/search ATH LON")
    assert "Usage" in bot.telegram.last_text
    await bot.send("/search ATH LON someday")
    assert "couldn't read that date" in bot.telegram.last_text
    await bot.send("/search ATH LON 2020-01-01")
    assert "in the past" in bot.telegram.last_text


async def test_stop_button_cancels_running_search(bot, provider):
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_search(*args, **kwargs):
        started.set()
        await release.wait()
        return []
    provider.search_flights = slow_search

    await bot.send(f"/search ATH LON {future(10)}..{future(12)}")
    assert bot.telegram.button_data("Stop") == "task:stop"
    task = bot.user_data["running_task"]
    await started.wait()
    await bot.press("task:stop")
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert "Search stopped" in bot.telegram.last_text


async def test_cancel_button_and_command_end_wizard(bot):
    await bot.send("/search")
    await bot.press("cancel")
    assert bot.telegram.last_text == "❌ Cancelled."
    sent_before = len(bot.telegram.calls)
    await bot.send("Athens")
    assert len(bot.telegram.calls) == sent_before

    await bot.send("/search")
    await bot.send("/cancel")
    assert bot.telegram.last_text == "❌ Cancelled."
    sent_before = len(bot.telegram.calls)
    await bot.send("Athens")
    assert len(bot.telegram.calls) == sent_before


async def test_starting_another_wizard_ends_the_first(bot):
    await bot.send("/search")
    await bot.send("/track")
    replies_before = len(bot.telegram.texts)
    await bot.send("Athens")
    assert len(bot.telegram.texts) == replies_before + 1
    await bot.press(bot.telegram.button_data("ATH"))
    assert "Step 2/6" in bot.telegram.last_text
