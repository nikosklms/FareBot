import asyncio

from bot.lifecycle import RESTART_NOTICE, request_stop
from daemon.scheduler import schedule_digest
from tests.fakes import USER_ID, future


def block_searches(provider):
    started, never = asyncio.Event(), asyncio.Event()

    async def blocked(*args, **kwargs):
        started.set()
        await never.wait()
        return []
    provider.search_flights = blocked
    return started


async def test_stop_cancels_running_search_and_explains(bot, provider):
    started = block_searches(provider)
    await bot.send(f"/search ATH LON {future(5)}..{future(9)}")
    task = bot.user_data["running_task"]
    await started.wait()

    request_stop(bot.app)
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert bot.telegram.last_text == RESTART_NOTICE
    assert bot.services.shutting_down


async def test_stop_interrupts_running_digest(bot, provider):
    started = block_searches(provider)
    digest = await bot.services.db.create_digest(USER_ID, "ATH", "oceania", days_ahead=3, delivery_day="Friday",
                                                 delivery_time="21:46")

    schedule_digest(bot.app.job_queue, digest, bot.services.timezone)
    [job] = bot.app.job_queue.get_jobs_by_name(f"digest_job_{digest.id}")
    task = asyncio.create_task(job.run(bot.app))  # digest_job, as at delivery time
    await started.wait()

    request_stop(bot.app)
    await asyncio.gather(task, return_exceptions=True)

    assert "interrupted because the bot restarted" in bot.telegram.last_text
    assert "next Friday at 21:46" in bot.telegram.last_text


async def test_stop_is_idempotent_and_safe_when_idle(bot):
    request_stop(bot.app)
    request_stop(bot.app)
    assert bot.services.shutting_down


async def test_startup_continues_when_the_command_menus_fail(bot):
    from main import on_startup
    bot.telegram.failing.add("setMyCommands")
    await on_startup(bot.app)  # used to stop the bot with "chat not found"
    assert bot.telegram.calls_to("setMyCommands")
