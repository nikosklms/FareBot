import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("FAREST_DB_PATH", str(BASE_DIR / "farebot.db"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Polling configuration
MIN_POLL_INTERVAL_HOURS = 6
DEFAULT_POLL_INTERVAL_HOURS = 6
MAX_TRACKERS_PER_USER = 5
MAX_CONSECUTIVE_FAILURES = 3
