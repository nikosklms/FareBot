import re

import pytest

from tests.fakes import USER_ID, future

# Each wizard: its command, total steps, and the answers that reach the last step.
# An answer starting with ">" is typed; anything else is a button press.
WIZARDS = {
    "search": ("/search", 4, [">ATH", "src:org:ATH", ">LON", "src:dst:LON", f">{future(10)}"]),
    "track": ("/track", 6, [">ATH", "trk:org:ATH", ">LON", "trk:dst:LON", f">{future(10)}", "trk:direct:1", ">150"]),
    "explore": ("/explore", 6, ["exp:org:ATH", "exp:reg:europe", "exp:sort:both", "exp:when:days:7", "exp:direct:0"]),
    "digest": ("/digest", 9, ["dig:org:ATH", "dig:reg:europe", "dig:sort:both", "dig:bud:80", "dig:when:days:30",
                              "dig:direct:1", "dig:day:Friday", "dig:time:18:00"]),
}


async def answer(bot, step: str) -> None:
    if step.startswith(">"):
        await bot.send(step[1:])
    else:
        await bot.press(step)


def current_step(bot) -> int:
    return int(re.search(r"Step (\d+)/", bot.telegram.last_text).group(1))


@pytest.mark.parametrize("wizard", WIZARDS)
async def test_back_walks_every_step_to_the_first(bot, wizard):
    command, total, answers = WIZARDS[wizard]
    await bot.send(command)
    assert "back" not in [data for _, data in bot.telegram.last_buttons()]
    for step in answers:
        await answer(bot, step)
    assert current_step(bot) == total

    for expected in range(total - 1, 0, -1):
        assert ("⬅️ Back", "back") in bot.telegram.last_buttons()
        await bot.press("back")
        assert current_step(bot) == expected

    assert "back" not in [data for _, data in bot.telegram.last_buttons()]
    await bot.press("back")
    assert current_step(bot) == 1


async def test_going_back_keeps_earlier_answers_and_can_finish(bot):
    command, _, answers = WIZARDS["track"]
    await bot.send(command)
    for step in answers:
        await answer(bot, step)
    await bot.press("back")
    await bot.press("back")
    assert "Step 4/6" in bot.telegram.last_text and future(10) in bot.telegram.last_text

    await bot.press("trk:direct:0")
    await bot.send("99")
    await bot.press("trk:freq:12")
    [tracker] = await bot.services.db.list_trackers(USER_ID)
    assert (tracker.direct_only, tracker.max_budget, tracker.frequency_hours) == (False, 99.0, 12)


async def test_back_from_destination_shows_the_chosen_origin(bot):
    await bot.send("/search")
    await bot.send("ATH")
    await bot.press("src:org:ATH")
    await bot.send("LON")
    await bot.press("src:dst:LON")
    await bot.press("back")
    assert "<b>From</b>: ATH" in bot.telegram.last_text and "Step 2/4" in bot.telegram.last_text
    await bot.send("PAR")
    await bot.press("src:dst:PAR")
    assert "ATH ✈️ PAR" in bot.telegram.last_text


async def test_back_from_airport_choices(bot):
    await bot.send("/search")
    await bot.send("ATH")
    await bot.press("src:org:ATH")
    await bot.send("london")
    assert ("⬅️ Back", "back") in bot.telegram.last_buttons()
    await bot.press("back")
    assert "Step 1/4" in bot.telegram.last_text


@pytest.mark.parametrize("command, answers, calendar", [
    ("/search", [">ATH", "src:org:ATH", ">LON", "src:dst:LON"], "src:date:cal"),
    ("/explore", ["exp:org:ATH", "exp:reg:asia", "exp:sort:price"], "exp:when:cal"),
])
async def test_back_inside_calendar_returns_to_the_same_step(bot, command, answers, calendar):
    await bot.send(command)
    for step in answers:
        await answer(bot, step)
    step_before = current_step(bot)
    await bot.press(f"{calendar}:open")
    await bot.press(f"{calendar}:day:{future(5)}")
    assert ("⬅️ Back", f"{calendar}:close") in bot.telegram.last_buttons()

    await bot.press(f"{calendar}:close")
    assert current_step(bot) == step_before
    assert "calendar" not in bot.user_data


async def test_back_after_the_wizard_ended_does_nothing(bot):
    await bot.send("/search")
    await bot.press("cancel")
    calls = len(bot.telegram.calls)
    await bot.press("back")
    assert len(bot.telegram.calls) == calls


async def test_a_wizard_replaced_by_the_editor_says_so_instead_of_going_silent(bot):
    from tests.test_search import start_to_dates
    tracker = await bot.services.db.create_tracker(USER_ID, "ATH", "LON", future(5), 100.0)
    await start_to_dates(bot)
    search_message = bot.telegram.last_message_id
    await bot.press(f"dash:edit:t:{tracker.id}", message_id=900)
    await bot.press("edit:done", message_id=900)

    await bot.press("src:date:preset:next_7_days", message_id=search_message)
    assert "replaced by a newer one. Start again with /search" in bot.telegram.alerts[-1]


async def test_typing_into_a_replaced_wizard_gets_an_answer(bot):
    from tests.test_search import start_to_dates
    tracker = await bot.services.db.create_tracker(USER_ID, "ATH", "LON", future(5), 100.0)
    await start_to_dates(bot)
    await bot.press(f"dash:edit:t:{tracker.id}", message_id=900)
    await bot.press("edit:done", message_id=900)
    await bot.send(future(3))  # the search wizard's date step was left open behind the editor
    assert bot.telegram.last_text == "That wizard was closed. Start again with /search."


async def test_an_old_calendars_buttons_dont_crash(bot):
    from tests.test_search import start_to_dates
    await start_to_dates(bot)
    await bot.press("src:date:cal:open")
    old_calendar = bot.telegram.last_message_id
    await start_to_dates(bot)  # a new /search clears the calendar state
    await bot.press("src:date:cal:mode:single", message_id=old_calendar)
    assert "Something went wrong" not in bot.telegram.last_text
    assert "Pick the departure date" in bot.telegram.last_text
