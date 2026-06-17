"""
main.py — نقطة دخول البوت الرئيسية
- تهيئة جميع المكونات
- تسجيل المعالجات
- مهام الصيانة الدورية
- إيقاف نظيف عند إنهاء التشغيل
"""

import asyncio
import logging
import sys

from pyrogram import Client, idle
from pytgcalls import PyTgCalls

from .config import (
    API_HASH,
    API_ID,
    ASSISTANT_SESSION,
    BOT_TOKEN,
    DB_PATH,
    OWNER_ID,
)
from .database import Database
from .handlers import (
    register_developer_handlers,
    register_general_handlers,
    register_group_handlers,
)
from .logger_utils import send_log, setup_logging
from .player import MusicPlayer
from .rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


def _validate_config() -> None:
    """التحقق من الإعدادات الجوهرية فور الاستيراد."""
    if API_ID == 0:
        sys.exit("[CONFIG ERROR] API_ID غير صالح — يجب أن يكون رقماً صحيحاً موجباً.")
    if OWNER_ID == 0:
        sys.exit("[CONFIG ERROR] OWNER_ID غير صالح.")
    logger.info("الإعدادات تحققت بنجاح.")


async def _maintenance_loop(db: Database) -> None:
    """مهام صيانة دورية تعمل في الخلفية."""
    while True:
        try:
            await asyncio.sleep(3600)
            db.cleanup_old_stats(days=30)
            await rate_limiter.cleanup()
            logger.info("دورة الصيانة الدورية اكتملت.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("خطأ في دورة الصيانة: %s", e)


async def main() -> None:
    setup_logging()
    _validate_config()

    logger.info("=" * 60)
    logger.info("بدء تشغيل البوت...")
    logger.info("=" * 60)

    # ── قاعدة البيانات ─────────────────────────────
    db = Database(DB_PATH)

    # ── عملاء Pyrogram ─────────────────────────────
    bot = Client(
        "music_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
    )

    assistant = Client(
        "assistant",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=ASSISTANT_SESSION,
    )

    # ── PyTgCalls ─────────────────────────────
    calls = PyTgCalls(assistant)
    player = MusicPlayer(calls)

    # ── حدث انتهاء البث (FIXED) ─────────────────────────────
    @calls.on_update()
    async def _stream_end_handler(client, update):
        try:
            chat_id = getattr(update, "chat_id", None)

            if not chat_id:
                return

            logger.info("[%s] انتهى البث — الانتقال للتالية.", chat_id)

            next_song = await player.on_stream_end(chat_id)

            if next_song:
                logger.info("[%s] يعمل الآن: %s", chat_id, next_song.title)

                await send_log(
                    bot,
                    f"⏭ انتقال تلقائي\n"
                    f"المجموعة: {chat_id}\n"
                    f"الأغنية: {next_song.title}",
                )
            else:
                logger.info("[%s] انتهت جميع الأغاني — مغادرة المكالمة.", chat_id)

        except Exception as e:
            logger.exception("خطأ في معالج انتهاء البث: %s", e)

    # ── تسجيل المعالجات ─────────────────────────────
    register_general_handlers(bot)
    register_developer_handlers(bot, db)
    register_group_handlers(bot, db, player)

    # ── تشغيل الخدمات ─────────────────────────────
    logger.info("بدء تشغيل البوت...")
    await bot.start()

    logger.info("بدء تشغيل المساعد...")
    await assistant.start()

    logger.info("بدء تشغيل PyTgCalls...")
    await calls.start()

    # ── إشعار التشغيل ─────────────────────────────
    try:
        await bot.send_message(
            OWNER_ID,
            "✅ البوت بدأ التشغيل بنجاح!\n\n"
            f"قاعدة البيانات: {DB_PATH}\n"
            f"المجموعات: {db.count_groups()}\n"
            f"إجمالي التشغيلات: {db.count_total_plays()}",
        )
    except Exception:
        pass

    logger.info("✅ البوت يعمل الآن!")

    # ── مهام خلفية ─────────────────────────────
    maintenance_task = asyncio.create_task(_maintenance_loop(db))

    try:
        await idle()
    finally:
        logger.info("جاري الإيقاف...")

        maintenance_task.cancel()
        try:
            await maintenance_task
        except asyncio.CancelledError:
            pass

        try:
            await calls.stop()
        except Exception:
            pass

        try:
            await assistant.stop()
        except Exception:
            pass

        try:
            await bot.stop()
        except Exception:
            pass

        logger.info("تم الإيقاف بنجاح.")


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("تم الإيقاف يدويًا.")
    except Exception as e:
        logger.critical("خطأ فادح: %s", e, exc_info=True)
        sys.exit(1)
