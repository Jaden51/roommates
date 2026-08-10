import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

DB_PATH = BASE_DIR / "data" / "roommates.db"
DB_DSN = f"sqlite+aiosqlite:///{DB_PATH}"

DEFAULT_REMINDER_HOUR = int(os.environ.get("REMINDER_HOUR", "8"))
DEFAULT_REMINDER_MINUTE = int(os.environ.get("REMINDER_MINUTE", "0"))
DEFAULT_TZ = os.environ.get("TZ", "UTC")

MONEY_PRECISION = 100  # cents per whole unit
