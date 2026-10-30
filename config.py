import logging
import os
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values, load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DB_PATH = os.getenv("FAREST_DB_PATH", str(BASE_DIR / "farebot.db"))
HEALTH_CHECK_PORT = int(os.getenv("PORT", "10000"))
LOGS_DIR = BASE_DIR / "logs"

MIN_POLL_INTERVAL_HOURS = 6
MAX_TRACKERS_PER_USER = 20
MAX_CONSECUTIVE_FAILURES = 3


def get_timezone() -> tzinfo:
    """Timezone for digest delivery times: TIMEZONE env var, else the server's named zone.

    A named zone (e.g. Europe/Athens) follows daylight saving time; the fixed-offset
    fallback does not, so set TIMEZONE on hosts without /etc/localtime.
    """
    name = os.getenv("TIMEZONE")
    if name:
        return ZoneInfo(name)
    localtime = Path("/etc/localtime")
    if localtime.is_symlink() and "zoneinfo/" in str(localtime.resolve()):
        try:
            return ZoneInfo(str(localtime.resolve()).split("zoneinfo/", 1)[1])
        except (ValueError, KeyError, OSError):
            pass
    return datetime.now().astimezone().tzinfo


def get_allowed_users() -> list[int]:
    """Read ALLOWED_USERS fresh on every call so edits to .env apply without a restart."""
    raw = dotenv_values(BASE_DIR / ".env").get("ALLOWED_USERS") or os.getenv("ALLOWED_USERS", "")
    return [int(uid) for uid in (part.strip() for part in raw.split(",")) if uid.isdigit()]


def check_config() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN is not set. Add it to .env or the environment.")
    if not get_allowed_users():
        logger.warning("ALLOWED_USERS is empty: nobody will be able to use the bot.")
