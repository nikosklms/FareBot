from providers.base import FlightOffer
from tests.fakes import future


async def to_destination_step(bot):
    await bot.send("/search")
    await bot.send("SKG")
    await bot.press("src:org:SKG")


async def test_region_button_continues_as_explore(bot, provider):
    provider.offers = lambda o, d, day: [FlightOffer(o, d, day, price=40.0, airline="Air")] if d == "FCO" else []
    await to_destination_step(bot)
    assert bot.telegram.button_data("Whole Region") == "src:regions"

    await bot.press("src:regions")
    assert "Which region?" in bot.telegram.last_text
    await bot.press("exp:from:SKG:europe")
    assert "Step 3/5" in bot.telegram.last_text and "Europe" in bot.telegram.last_text

    await bot.press("exp:sort:price")
    await bot.press("exp:when:days:2")
    await bot.press("exp:lim:5")
    await bot.finish_background_task()
    assert "Deals from SKG to Europe" in bot.telegram.last_text
    assert {origin for origin, _, _, _ in provider.queries} == {"SKG"}


async def test_typed_region_offers_explore(bot):
    await to_destination_step(bot)
    await bot.send("Latin America")
    assert "is a whole region" in bot.telegram.last_text
    assert bot.telegram.button_data("Explore Latin America") == "exp:from:SKG:latin_america"
    await bot.press("exp:from:SKG:latin_america")
    assert "Step 3/5" in bot.telegram.last_text


async def test_back_from_region_picker_returns_to_destination(bot):
    await to_destination_step(bot)
    await bot.press("src:regions")
    await bot.press("src:regions:close")
    assert "Step 2/4" in bot.telegram.last_text


async def test_typing_a_city_still_searches_flights(bot):
    await to_destination_step(bot)
    await bot.send("london")
    assert "Which airport do you mean?" in bot.telegram.last_text
    await bot.press("src:dst:LON")
    assert "Step 3/4" in bot.telegram.last_text


async def test_after_handoff_only_explore_answers(bot):
    await to_destination_step(bot)
    await bot.press("src:regions")
    await bot.press("exp:from:SKG:asia")
    await bot.press("exp:sort:both")
    replies = len(bot.telegram.texts)
    await bot.send("30")
    assert len(bot.telegram.texts) == replies + 1
    assert f"{future(1)} ➔ {future(30)}" in bot.telegram.last_text
