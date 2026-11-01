from tests.fakes import USER_ID, future


async def only_digest(bot):
    [digest] = await bot.services.db.list_digests(USER_ID)
    return digest


async def test_full_wizard_creates_and_schedules_digest(bot):
    await bot.send("/digest")
    assert "Step 1/9" in bot.telegram.last_text
    await bot.press("dig:org:ATH")
    await bot.press("dig:reg:latin_america")
    await bot.press("dig:sort:price")
    await bot.send("cheap")
    assert "Type an amount" in bot.telegram.last_text
    await bot.send("120")
    assert "Step 5/9" in bot.telegram.last_text
    await bot.press("dig:when:days:60")
    await bot.press("dig:direct:1")
    await bot.press("dig:day:Friday")
    await bot.send("25:00")
    assert "Type a time" in bot.telegram.last_text
    await bot.send("8:30")
    await bot.press("dig:lim:5")

    digest = await only_digest(bot)
    assert (digest.origin_code, digest.region, digest.sort_mode, digest.max_budget) == ("ATH", "latin_america", "price", 120.0)
    assert (digest.days_ahead, digest.delivery_day, digest.delivery_time, digest.max_results) == (60, "Friday", "08:30", 5)
    assert digest.direct_only and "Direct flights only" in bot.telegram.last_text
    assert "Weekly digest scheduled" in bot.telegram.last_text
    assert bot.jobs("digest_job_") == [f"digest_job_{digest.id}"]


async def test_fixed_dates_and_any_budget(bot):
    await bot.send("/digest")
    await bot.press("dig:org:SKG")
    await bot.press("dig:reg:europe")
    await bot.press("dig:sort:both")
    await bot.press("dig:bud:0")
    await bot.press("dig:when:cal:open")
    await bot.press(f"dig:when:cal:day:{future(30)}")
    await bot.press(f"dig:when:cal:day:{future(40)}")
    await bot.press("dig:direct:0")
    await bot.press("dig:day:Sunday")
    await bot.press("dig:time:15:00")
    await bot.press("dig:lim:10")

    digest = await only_digest(bot)
    assert digest.max_budget is None and digest.days_ahead is None and not digest.direct_only
    assert (digest.departure_date, digest.departure_date_end) == (future(30), future(40))


async def test_shortcut_defaults(bot):
    await bot.send("/digest ATH europe")
    digest = await only_digest(bot)
    assert (digest.days_ahead, digest.max_budget, digest.delivery_day, digest.delivery_time) == (30, None, "Sunday", "15:00")
    assert (digest.sort_mode, digest.max_results) == ("both", 10)


async def test_shortcut_all_arguments(bot):
    await bot.send("/digest ATH asia 60 80 friday@18:00 5")
    digest = await only_digest(bot)
    assert (digest.region, digest.days_ahead, digest.max_budget) == ("asia", 60, 80.0)
    assert (digest.delivery_day, digest.delivery_time, digest.max_results) == ("Friday", "18:00", 5)


async def test_shortcut_rejects_bad_input(bot):
    for bad in ["/digest ATH", "/digest ATH moon", "/digest ATH europe Funday@15:00", "/digest ATH europe 30 x"]:
        await bot.send(bad)
        assert "Usage" in bot.telegram.last_text, bad
    assert await bot.services.db.list_digests(USER_ID) == []


async def test_duplicate_digest_is_refused(bot):
    await bot.send("/digest ATH europe 30 50 Monday@09:00")
    await bot.send("/digest ATH europe 30 50 Monday@09:00")
    assert "already have this digest" in bot.telegram.last_text
    await bot.send("/digest ATH europe 30 80 Monday@09:00")
    assert "Weekly digest scheduled" in bot.telegram.last_text  # a different budget is a different digest
    assert len(await bot.services.db.list_digests(USER_ID)) == 2
