"""
logger_utils.py — إعداد نظام السجلات وإرسالها لقروب التيليجرام
"""

import logging
import sys
from datetime import datetime
from typing import Optional

from .config import LOG_GROUP_ID, LOG_LEVEL


def setup_logging() -> None:
    """إعداد نظام السجلات لملف وconsole معاً."""
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
    ]

    # حفظ السجلات في ملف
    try:
        fh = logging.FileHandler("bot.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        handlers.append(fh)
    except OSError as e:
        print(f"[WARNING] تعذّر فتح ملف السجلات: {e}")

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
    )

    # تخفيف ضجيج مكتبات خارجية
    for noisy in ("pyrogram", "pytgcalls", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def send_log(client, text: str, level: str = "INFO") -> None:
    """
    إرسال رسالة سجل إلى قروب التيليجرام إن وُجد.

    Args:
        client: عميل Pyrogram النشط.
        text: نص السجل.
        level: مستوى السجل (INFO, WARNING, ERROR).
    """
    if not LOG_GROUP_ID:
        return

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    icons = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "🔴", "DEBUG": "🔍"}
    icon = icons.get(level.upper(), "📋")

    log_text = (
        f"{icon} سجل جديد\n\n"
        f"{text}\n\n"
        f"🕐 الوقت: {now}"
    )

    try:
        await client.send_message(LOG_GROUP_ID, log_text)
    except Exception as e:
        logging.getLogger(__name__).warning("فشل إرسال السجل: %s", e)
