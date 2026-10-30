"""Stopping the bot without waiting for long searches.

python-telegram-bot waits for every running job and background task before it exits,
and a large /explore or digest can run for half an hour. On Ctrl+C or SIGTERM the bot
cancels that work first; each search tells its user why it stopped.
"""
import asyncio
import logging
import signal
from typing import Optional

from telegram.ext import Application

from bot.services import SERVICES_KEY

logger = logging.getLogger(__name__)

RUNNING_KEY = "running_tasks"
RESTART_NOTICE = "⏹ Stopped because the bot is restarting. Please try again in a minute."


def track_task(application: Application, task: Optional[asyncio.Task] = None) -> None:
    """Register a search, digest or check to be cancelled on shutdown."""
    task = task or asyncio.current_task()
    running: set[asyncio.Task] = application.bot_data.setdefault(RUNNING_KEY, set())
    running.add(task)
    task.add_done_callback(running.discard)


def request_stop(application: Application) -> None:
    services = application.bot_data[SERVICES_KEY]
    if services.shutting_down:
        return
    services.shutting_down = True
    running = list(application.bot_data.get(RUNNING_KEY, ()))
    logger.info("Stopping: cancelling %d running searches", len(running))
    for task in running:
        task.cancel()
    if application.running:
        application.stop_running()


def install_stop_signals(application: Application) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_stop, application)
