"""Finished searches arrive as new messages, which notify; edits don't."""
from daemon.scheduler import send_digest
from providers.base import FlightOffer
from tests.fakes import USER_ID, future


def offers(origin, destination, day):
    return [FlightOffer(origin, destination, day, price=40.0, airline="Air")] if destination in ("LON", "FCO") else []


def results_were_sent_and_progress_deleted(bot, results: str) -> None:
    sent = bot.telegram.calls_to("sendMessage")
    assert results in sent[-1]["text"]
    assert not any(results in edit["text"] for edit in bot.telegram.calls_to("editMessageText"))
    [deleted] = bot.telegram.calls_to("deleteMessage")  # the progress message, not the results
    assert deleted["message_id"] != bot.telegram.last_message_id


async def test_search_results_arrive_as_a_new_message(bot, provider):
    provider.offers = offers
    await bot.send(f"/search ATH LON {future(5)}..{future(7)}")
    await bot.finish_background_task()
    results_were_sent_and_progress_deleted(bot, "Top 3 flights")
    assert bot.telegram.button_data("Track This Route")


async def test_no_results_notify_too(bot, provider):
    await bot.send(f"/search ATH LON {future(5)}")
    await bot.finish_background_task()
    results_were_sent_and_progress_deleted(bot, "No flights found")


async def test_explore_results_arrive_as_a_new_message(bot, provider):
    provider.offers = offers
    await bot.send("/explore ATH europe 2")
    await bot.finish_background_task()
    results_were_sent_and_progress_deleted(bot, "ATH ✈️ FCO")
    await bot.press("deals:show", message_id=bot.telegram.last_message_id)
    assert bot.telegram.button_data("Track #1")  # the Track buttons belong to the new message


async def test_a_digest_starts_silently_and_notifies_with_its_results(bot, provider):
    provider.offers = offers
    digest = await bot.services.db.create_digest(USER_ID, "ATH", "europe", days_ahead=2)
    await send_digest(bot.services, bot.app.bot, digest.id)

    start, results = bot.telegram.calls_to("sendMessage")
    assert "Searching deals" in start["text"] and start.get("disable_notification") is True
    assert "ATH ✈️ FCO" in results["text"] and not results.get("disable_notification")
    assert len(bot.telegram.calls_to("deleteMessage")) == 1


async def test_progress_stays_when_the_results_cant_be_sent(bot, provider):
    provider.offers = offers
    await bot.send("/explore ATH europe 2")
    bot.telegram.sending_fails = True
    await bot.finish_background_task()
    assert not bot.telegram.calls_to("deleteMessage")  # the user still sees where it got to
