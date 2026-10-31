import fcntl
import logging
import sys
from typing import IO, Optional

from telegram import BotCommandScopeChat, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder, Defaults
from telegram.request import BaseRequest

from bot.auth import admin_id
from bot.handlers import ADMIN_COMMANDS, BOT_COMMANDS, register_handlers
from bot.lifecycle import install_stop_signals
from bot.services import SERVICES_KEY, Services
from config import BASE_DIR, DB_PATH, TELEGRAM_BOT_TOKEN, check_config, get_timezone
from daemon.scheduler import register_jobs
from database.db import Database
from providers.fast_flights import FastFlightsProvider
from services.resolver import LocationResolver

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def acquire_instance_lock() -> IO[str]:
    """Exit if another FareBot process already holds the lock: two pollers would fight over updates."""
    lock_file = open(BASE_DIR / "farebot.lock", "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.error("Another FareBot instance is already running. Exiting.")
        sys.exit(1)
    return lock_file


async def on_startup(app: Application) -> None:
    services: Services = app.bot_data[SERVICES_KEY]
    await services.db.migrate()
    # The command menus are a convenience: if Telegram refuses (e.g. the admin never opened the
    # bot, so their chat doesn't exist yet), keep going rather than stop the bot.
    try:
        await app.bot.set_my_commands(BOT_COMMANDS)
        if admin_id():  # the admin's menu also lists /users and /stats
            await app.bot.set_my_commands(BOT_COMMANDS + ADMIN_COMMANDS, scope=BotCommandScopeChat(admin_id()))
    except TelegramError:
        logger.warning("Couldn't set the command menus; commands still work when typed", exc_info=True)
    await register_jobs(app)
    install_stop_signals(app)


async def on_shutdown(app: Application) -> None:
    await app.bot_data[SERVICES_KEY].provider.close()


def build_application(services: Services, token: str = TELEGRAM_BOT_TOKEN,
                      request: Optional[BaseRequest] = None) -> Application:
    defaults = Defaults(parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True))
    builder = ApplicationBuilder().token(token).defaults(defaults).post_init(on_startup).post_shutdown(on_shutdown)
    if request:
        builder = builder.request(request).get_updates_request(request)
    app = builder.build()
    app.bot_data[SERVICES_KEY] = services
    register_handlers(app)
    return app


def main() -> None:
    lock = acquire_instance_lock()  # noqa: F841 - held open for the life of the process
    check_config()
    services = Services(
        db=Database(DB_PATH),
        provider=FastFlightsProvider(),
        resolver=LocationResolver(),
        timezone=get_timezone(),
    )
    logger.info("FareBot is starting")
    # Stop signals are handled by install_stop_signals, which cancels running searches first.
    build_application(services).run_polling(drop_pending_updates=True, stop_signals=None)


if __name__ == "__main__":
    main()
