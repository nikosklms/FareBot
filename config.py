import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

# Automatically load environment variables from .env if present
load_dotenv(BASE_DIR / ".env")

DB_PATH = os.getenv("FAREST_DB_PATH", str(BASE_DIR / "farebot.db"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

def get_allowed_users() -> list[int]:
    """Dynamically load ALLOWED_USERS from .env file so additions take effect instantly."""
    load_dotenv(BASE_DIR / ".env", override=True)
    raw_users = os.getenv("ALLOWED_USERS", "")
    return [int(uid.strip()) for uid in raw_users.split(",") if uid.strip().isdigit()]

ALLOWED_USERS = get_allowed_users()

# Polling configuration
MIN_POLL_INTERVAL_HOURS = 6
DEFAULT_POLL_INTERVAL_HOURS = 6
MAX_TRACKERS_PER_USER = 5
MAX_CONSECUTIVE_FAILURES = 3

def check_config():
    """Verify essential configuration parameters are present."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN is not set. Please add it to your .env file or environment variables.")
