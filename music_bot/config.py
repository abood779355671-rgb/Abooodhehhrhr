"""
config.py — التحقق من متغيرات البيئة وإعدادات البوت
"""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _require(key: str, cast=str):
    """اقرأ متغير بيئة مطلوب أو أوقف البرنامج بخطأ واضح."""
    val = os.getenv(key)
    if not val:
        logger.critical("متغير البيئة المطلوب مفقود: %s", key)
        sys.exit(f"[CONFIG ERROR] المتغير المطلوب غير موجود في ملف .env: {key}")
    try:
        return cast(val)
    except (ValueError, TypeError):
        sys.exit(f"[CONFIG ERROR] قيمة {key} غير صالحة: {val!r}")


def _optional(key: str, default=None, cast=str):
    val = os.getenv(key)
    if not val:
        return default
    try:
        return cast(val)
    except (ValueError, TypeError):
        logger.warning("قيمة %s غير صالحة: %r — سيتم استخدام القيمة الافتراضية.", key, val)
        return default


# ── مفاتيح Telegram الأساسية ──────────────────────────────────────────────
API_ID: int = _require("API_ID", cast=int)
API_HASH: str = _require("API_HASH")
BOT_TOKEN: str = _require("BOT_TOKEN")
ASSISTANT_SESSION: str = _require("ASSISTANT_SESSION")
OWNER_ID: int = _require("OWNER_ID", cast=int)

# ── إعدادات اختيارية ──────────────────────────────────────────────────────
LOG_GROUP_ID: int | None = _optional("LOG_GROUP_ID", cast=int)

# ── مسارات الملفات ────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).parent
DB_PATH: Path = BASE_DIR / "bot_data.sqlite3"

# ── حدود قائمة الانتظار ──────────────────────────────────────────────────
MAX_QUEUE_SIZE: int = _optional("MAX_QUEUE_SIZE", default=50, cast=int)
MAX_SONG_DURATION: int = _optional("MAX_SONG_DURATION", default=1800, cast=int)  # 30 دقيقة

# ── Rate Limiting ────────────────────────────────────────────────────────
RATE_LIMIT_PLAY: int = _optional("RATE_LIMIT_PLAY", default=10, cast=int)  # ثانية بين الطلبات
RATE_LIMIT_WINDOW: int = _optional("RATE_LIMIT_WINDOW", default=60, cast=int)  # نافذة زمنية
MAX_REQUESTS_PER_WINDOW: int = _optional("MAX_REQUESTS_PER_WINDOW", default=5, cast=int)

# ── yt-dlp ───────────────────────────────────────────────────────────────
YTDLP_RETRIES: int = _optional("YTDLP_RETRIES", default=3, cast=int)
URL_REFRESH_BEFORE_EXPIRY: int = 300  # تحديث الرابط قبل 5 دقائق من انتهاء صلاحيته

# ── إعدادات السجلات ──────────────────────────────────────────────────────
LOG_LEVEL: str = _optional("LOG_LEVEL", default="INFO")
