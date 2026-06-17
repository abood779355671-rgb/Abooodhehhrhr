"""
handlers.py — جميع معالجات أوامر البوت
- أوامر المجموعة (تشغيل، تخطي، إيقاف، القائمة، الان، ريبورت)
- لوحة المطور (panel)
- حماية الصلاحيات
- Rate Limiting
"""

import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatMembersFilter
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .config import OWNER_ID
from .database import Database
from .logger_utils import send_log
from .player import MusicPlayer
from .rate_limiter import rate_limiter
from .youtube import search_audio

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# أدوات مساعدة
# ─────────────────────────────────────────────────────────────────────────────

async def _is_admin(
    client: Client, db: Database, chat_id: int, user_id: int
) -> bool:
    """التحقق من صلاحيات المشرف — يتحقق من DB أولاً ثم API."""
    # OWNER_ID دائماً مشرف
    if user_id == OWNER_ID:
        return True

    # الفحص من قاعدة البيانات (cache)
    if db.is_saved_admin(chat_id, user_id):
        return True

    # الرجوع إلى API التيليجرام
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in {
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
        }
    except Exception:
        return False


def _format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "غير محدد"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ─────────────────────────────────────────────────────────────────────────────
# لوحة المطور
# ─────────────────────────────────────────────────────────────────────────────

def _developer_keyboard(db: Database) -> InlineKeyboardMarkup:
    enabled_text = "⏸ تعطيل البوت" if db.is_bot_enabled() else "▶️ تفعيل البوت"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 الإحصائيات", callback_data="dev_stats"),
            InlineKeyboardButton(enabled_text, callback_data="dev_toggle_bot"),
        ],
        [
            InlineKeyboardButton("🚫 حظر مجموعة", callback_data="dev_ban_help"),
            InlineKeyboardButton("✅ فك حظر مجموعة", callback_data="dev_unban_help"),
        ],
        [
            InlineKeyboardButton("📋 سجلات التشغيل", callback_data="dev_logs_info"),
            InlineKeyboardButton("🔄 تحديث اللوحة", callback_data="dev_refresh"),
        ],
    ])


def _panel_text(db: Database) -> str:
    status = "🟢 يعمل" if db.is_bot_enabled() else "🔴 متوقف"
    return (
        "🛠 لوحة المطور\n\n"
        f"حالة البوت: {status}\n"
        f"عدد المجموعات: {db.count_groups()}\n"
        f"المجموعات المحظورة: {db.count_banned_groups()}\n"
        f"عدد مرات التشغيل: {db.count_total_plays()}"
    )


def register_developer_handlers(bot: Client, db: Database) -> None:
    """تسجيل معالجات لوحة المطور."""

    @bot.on_message(filters.command("panel") & filters.private)
    async def developer_panel(client: Client, message: Message) -> None:
        if message.from_user.id != OWNER_ID:
            await message.reply_text("❌ هذه اللوحة خاصة بالمطور فقط.")
            return
        await message.reply_text(
            _panel_text(db),
            reply_markup=_developer_keyboard(db),
        )

    @bot.on_message(filters.regex(r"^لوحة$") & filters.private)
    async def developer_panel_arabic(client: Client, message: Message) -> None:
        if message.from_user.id != OWNER_ID:
            await message.reply_text("❌ هذه اللوحة خاصة بالمطور فقط.")
            return
        await message.reply_text(
            _panel_text(db),
            reply_markup=_developer_keyboard(db),
        )

    @bot.on_callback_query(filters.regex(r"^dev_"))
    async def developer_callbacks(
        client: Client, callback_query: CallbackQuery
    ) -> None:
        if callback_query.from_user.id != OWNER_ID:
            await callback_query.answer(
                "❌ هذه اللوحة خاصة بالمطور فقط.", show_alert=True
            )
            return

        data = callback_query.data

        if data in ("dev_stats", "dev_refresh"):
            label = "تم تحديث الإحصائيات" if data == "dev_stats" else "تم تحديث اللوحة"
            await callback_query.answer(label)
            await callback_query.message.edit_text(
                _panel_text(db),
                reply_markup=_developer_keyboard(db),
            )

        elif data == "dev_toggle_bot":
            current = db.is_bot_enabled()
            db.set_bot_enabled(not current)
            msg = "✅ تم تفعيل البوت" if not current else "⏸ تم تعطيل البوت"
            await callback_query.answer(msg)
            await callback_query.message.edit_text(
                _panel_text(db),
                reply_markup=_developer_keyboard(db),
            )

        elif data == "dev_ban_help":
            await callback_query.answer()
            await callback_query.message.reply_text(
                "لحظر مجموعة أرسل:\n\n"
                "<code>حظر -100123456789 السبب اختياري</code>",
                parse_mode="html",
            )

        elif data == "dev_unban_help":
            await callback_query.answer()
            await callback_query.message.reply_text(
                "لفك حظر مجموعة أرسل:\n\n"
                "<code>فك حظر -100123456789</code>",
                parse_mode="html",
            )

        elif data == "dev_logs_info":
            from .config import LOG_GROUP_ID
            await callback_query.answer()
            await callback_query.message.reply_text(
                "📋 حالة سجلات التشغيل:\n\n"
                f"LOG_GROUP_ID: <code>{LOG_GROUP_ID or 'غير محدد'}</code>\n\n"
                "لتغيير قروب السجلات عدّل القيمة في ملف .env ثم أعد تشغيل البوت.",
                parse_mode="html",
            )

    @bot.on_message(filters.text & filters.private)
    async def developer_private_commands(
        client: Client, message: Message
    ) -> None:
        if message.from_user.id != OWNER_ID:
            return

        text = message.text.strip()

        if text.startswith("حظر "):
            parts = text.split(maxsplit=2)
            if len(parts) < 2:
                await message.reply_text(
                    "استخدم:\n<code>حظر -100123456789 السبب اختياري</code>",
                    parse_mode="html",
                )
                return
            try:
                chat_id = int(parts[1])
            except ValueError:
                await message.reply_text("❌ معرف المجموعة غير صحيح.")
                return
            reason = parts[2] if len(parts) > 2 else ""
            try:
                chat = await client.get_chat(chat_id)
                title = chat.title or "غير محدد"
            except Exception:
                title = "غير محدد"
            db.ban_group(chat_id, title, reason)
            await message.reply_text(
                f"✅ تم حظر المجموعة.\n\n"
                f"المعرف: <code>{chat_id}</code>\n"
                f"العنوان: {title}\n"
                f"السبب: {reason or 'بدون سبب'}",
                parse_mode="html",
            )

        elif text.startswith("فك حظر "):
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                await message.reply_text(
                    "استخدم:\n<code>فك حظر -100123456789</code>",
                    parse_mode="html",
                )
                return
            try:
                chat_id = int(parts[2])
            except ValueError:
                await message.reply_text("❌ معرف المجموعة غير صحيح.")
                return
            db.unban_group(chat_id)
            await message.reply_text(
                f"✅ تم فك حظر المجموعة.\n\nالمعرف: <code>{chat_id}</code>",
                parse_mode="html",
            )


# ─────────────────────────────────────────────────────────────────────────────
# أوامر عامة (start)
# ─────────────────────────────────────────────────────────────────────────────

def register_general_handlers(bot: Client) -> None:
    """تسجيل الأوامر العامة."""

    @bot.on_message(filters.command("start") & filters.private)
    async def start_handler(client: Client, message: Message) -> None:
        await message.reply_text(
            "🎵 أهلاً بك في بوت تشغيل الأغاني!\n\n"
            "<b>الأوامر المتاحة في المجموعات:</b>\n"
            "▶️ <code>تشغيل اسم الأغنية</code> — تشغيل أغنية أو إضافتها للقائمة\n"
            "⏭ <code>تخطي</code> — تخطي الأغنية الحالية (للمشرفين)\n"
            "⏹ <code>ايقاف</code> — إيقاف التشغيل ومسح القائمة (للمشرفين)\n"
            "📋 <code>القائمة</code> — عرض قائمة الانتظار\n"
            "🎵 <code>الان</code> — الأغنية التي تعمل الآن\n"
            "👮 <code>ريبورت</code> — تحديث قائمة المشرفين (للمشرفين)\n\n"
            "<b>مثال:</b>\n"
            "<code>تشغيل نانسي عجرم</code>",
            parse_mode="html",
        )


# ─────────────────────────────────────────────────────────────────────────────
# أوامر المجموعة
# ─────────────────────────────────────────────────────────────────────────────

def register_group_handlers(
    bot: Client, db: Database, player: MusicPlayer
) -> None:
    """تسجيل جميع معالجات أوامر المجموعة."""

    @bot.on_message(filters.text & filters.group)
    async def group_commands(client: Client, message: Message) -> None:
        if not message.text or not message.from_user:
            return

        text = message.text.strip()
        chat_id = message.chat.id
        chat_title = message.chat.title or "بدون اسم"
        user_id = message.from_user.id
        user_name = message.from_user.first_name or "غير معروف"

        # تسجيل المجموعة
        db.save_group(chat_id, chat_title)

        # فحص حالة البوت والحظر
        if not db.is_bot_enabled() or db.is_group_banned(chat_id):
            return

        # ── تشغيل ──────────────────────────────────────────────────────────
        if text.startswith("تشغيل"):
            query = text[len("تشغيل"):].strip()
            if not query:
                await message.reply_text(
                    "❌ اكتب اسم الأغنية بعد الأمر.\n"
                    "مثال: <code>تشغيل نانسي عجرم</code>",
                    parse_mode="html",
                )
                return

            # Rate Limiting
            allowed, reason = await rate_limiter.check(chat_id, user_id)
            if not allowed:
                await message.reply_text(f"⏳ {reason}")
                return

            status_msg = await message.reply_text("🔍 جاري البحث...")

            try:
                song = await search_audio(query)
                result = await player.play_or_queue(chat_id, song)

                db.save_play_stat(
                    chat_id=chat_id,
                    chat_title=chat_title,
                    user_id=user_id,
                    user_name=user_name,
                    query=query,
                    song_title=song.title,
                )

                if result["status"] == "playing":
                    duration_str = _format_duration(song.duration)
                    await status_msg.edit_text(
                        f"▶️ يعمل الآن\n\n"
                        f"🎵 {song.title}\n"
                        f"⏱ المدة: {duration_str}"
                    )
                    await send_log(
                        client,
                        f"▶️ تشغيل مباشر\n"
                        f"المجموعة: {chat_title} ({chat_id})\n"
                        f"المستخدم: {user_name} ({user_id})\n"
                        f"البحث: {query}\n"
                        f"الأغنية: {song.title}\n"
                        f"المدة: {duration_str}",
                    )
                else:
                    pos = result["position"]
                    await status_msg.edit_text(
                        f"✅ تمت الإضافة إلى قائمة الانتظار\n\n"
                        f"🎵 {song.title}\n"
                        f"📍 الترتيب: {pos}\n"
                        f"⏱ المدة: {_format_duration(song.duration)}"
                    )
                    await send_log(
                        client,
                        f"📋 إضافة للقائمة\n"
                        f"المجموعة: {chat_title} ({chat_id})\n"
                        f"المستخدم: {user_name} ({user_id})\n"
                        f"الأغنية: {song.title}\n"
                        f"الترتيب: {pos}",
                    )

            except ValueError as e:
                # خطأ من المستخدم (مدة طويلة، قائمة ممتلئة...)
                await status_msg.edit_text(f"❌ {e}")
            except Exception as e:
                logger.exception("خطأ تشغيل [%d]: %s", chat_id, e)
                await status_msg.edit_text(
                    "❌ حدث خطأ أثناء التشغيل.\n"
                    "تأكد من وجود مكالمة صوتية وأن حساب المساعد داخل المجموعة."
                )
                await send_log(
                    client,
                    f"🔴 خطأ تشغيل\n"
                    f"المجموعة: {chat_title} ({chat_id})\n"
                    f"المستخدم: {user_name}\n"
                    f"البحث: {query}\n"
                    f"الخطأ: {type(e).__name__}: {e}",
                    level="ERROR",
                )

        # ── تخطي ───────────────────────────────────────────────────────────
        elif text == "تخطي":
            if not await _is_admin(client, db, chat_id, user_id):
                await message.reply_text("❌ هذا الأمر للمشرفين فقط.")
                return

            result = await player.skip(chat_id)

            if result["status"] == "not_playing":
                await message.reply_text("❌ لا توجد أغنية تعمل حالياً.")
            elif result["status"] == "stopped":
                await message.reply_text("⏹ تم التخطي — لا توجد أغنية بعدها.")
            else:
                song = result["song"]
                await message.reply_text(
                    f"⏭ تم التخطي\n\n"
                    f"🎵 يعمل الآن: {song.title}"
                )

            await send_log(
                client,
                f"⏭ أمر تخطي\n"
                f"المجموعة: {chat_title} ({chat_id})\n"
                f"المستخدم: {user_name}\n"
                f"الحالة: {result['status']}",
            )

        # ── إيقاف ──────────────────────────────────────────────────────────
        elif text in ("ايقاف", "إيقاف"):
            if not await _is_admin(client, db, chat_id, user_id):
                await message.reply_text("❌ هذا الأمر للمشرفين فقط.")
                return

            await player.stop(chat_id)
            await message.reply_text("⏹ تم إيقاف التشغيل ومسح قائمة الانتظار.")

            await send_log(
                client,
                f"⏹ أمر إيقاف\n"
                f"المجموعة: {chat_title} ({chat_id})\n"
                f"المستخدم: {user_name}",
            )

        # ── القائمة ────────────────────────────────────────────────────────
        elif text == "القائمة":
            queue = player.get_queue(chat_id)
            if not queue:
                await message.reply_text("📋 قائمة الانتظار فارغة.")
                return

            lines = ["📋 <b>قائمة التشغيل:</b>\n"]
            for i, song in enumerate(queue, 1):
                dur = _format_duration(song.duration)
                lines.append(f"{i}. {song.title} [{dur}]")

            await message.reply_text("\n".join(lines), parse_mode="html")

        # ── الان ───────────────────────────────────────────────────────────
        elif text == "الان":
            current = player.get_current(chat_id)
            if not current:
                await message.reply_text("❌ لا توجد أغنية تعمل حالياً.")
                return

            dur = _format_duration(current.duration)
            queue_size = player.queue_size(chat_id)
            await message.reply_text(
                f"🎵 <b>الأغنية الحالية:</b>\n\n"
                f"{current.title}\n"
                f"⏱ المدة: {dur}\n"
                f"📋 في القائمة: {queue_size} أغنية",
                parse_mode="html",
            )

        # ── ريبورت ─────────────────────────────────────────────────────────
        elif text == "ريبورت":
            if not await _is_admin(client, db, chat_id, user_id):
                await message.reply_text("❌ هذا الأمر للمشرفين فقط.")
                return

            status_msg = await message.reply_text("👮 جاري تحديث قائمة المشرفين...")

            try:
                count = await _refresh_group_admins(client, db, chat_id, chat_title)
                await status_msg.edit_text(
                    f"✅ تم تحديث قائمة المشرفين.\n\n"
                    f"عدد المشرفين: {count}"
                )
                await send_log(
                    client,
                    f"👮 تحديث المشرفين\n"
                    f"المجموعة: {chat_title} ({chat_id})\n"
                    f"المستخدم: {user_name}\n"
                    f"عدد المشرفين: {count}",
                )
            except Exception as e:
                logger.exception("خطأ تحديث مشرفين [%d]: %s", chat_id, e)
                await status_msg.edit_text("❌ حدث خطأ أثناء تحديث المشرفين.")
                await send_log(
                    client,
                    f"🔴 خطأ تحديث المشرفين\n"
                    f"المجموعة: {chat_title} ({chat_id})\n"
                    f"الخطأ: {type(e).__name__}: {e}",
                    level="ERROR",
                )


async def _refresh_group_admins(
    client: Client, db: Database, chat_id: int, chat_title: str
) -> int:
    """تحديث قائمة مشرفي المجموعة في قاعدة البيانات."""
    db.save_group(chat_id, chat_title)
    db.clear_admins(chat_id)
    count = 0

    async for member in client.get_chat_members(
        chat_id,
        filter=ChatMembersFilter.ADMINISTRATORS,
    ):
        user = member.user
        if user and not user.is_bot:
            name = " ".join(
                p for p in [user.first_name, user.last_name] if p
            )
            db.save_admin(
                chat_id=chat_id,
                user_id=user.id,
                name=name,
                status=str(member.status),
            )
            count += 1

    return count
