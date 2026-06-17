"""
player.py — إدارة مشغل الصوت وقوائم الانتظار
- قفل asyncio.Lock لكل مجموعة لمنع Race Conditions
- تحديث تلقائي لروابط yt-dlp المنتهية الصلاحية
- Retry عند فشل الاتصال بالمكالمة
- تنظيف تلقائي للمجموعات الخاملة
"""

import asyncio
import logging
from collections import defaultdict, deque
from typing import Dict, Optional

from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream

from .config import MAX_QUEUE_SIZE, URL_REFRESH_BEFORE_EXPIRY
from .youtube import SongInfo, refresh_url

logger = logging.getLogger(__name__)


class ChatPlayer:
    """حالة التشغيل لمجموعة واحدة."""

    __slots__ = ("queue", "current", "is_playing", "lock", "stream_lock")

    def __init__(self) -> None:
        self.queue: deque[SongInfo] = deque()
        self.current: Optional[SongInfo] = None
        self.is_playing: bool = False
        # قفل عمليات قائمة الانتظار
        self.lock: asyncio.Lock = asyncio.Lock()
        # قفل منع تكرار معالج انتهاء البث
        self.stream_lock: asyncio.Lock = asyncio.Lock()


class MusicPlayer:
    """
    المشغل الرئيسي — يحتفظ بحالة مستقلة لكل مجموعة.
    """

    def __init__(self, calls: PyTgCalls) -> None:
        self._calls = calls
        self._chats: Dict[int, ChatPlayer] = defaultdict(ChatPlayer)

    def _get(self, chat_id: int) -> ChatPlayer:
        return self._chats[chat_id]

    # ── API عام ────────────────────────────────────────────────────────────

    def is_playing(self, chat_id: int) -> bool:
        return self._chats[chat_id].is_playing

    def get_current(self, chat_id: int) -> Optional[SongInfo]:
        return self._chats[chat_id].current

    def get_queue(self, chat_id: int) -> list[SongInfo]:
        return list(self._chats[chat_id].queue)

    def queue_size(self, chat_id: int) -> int:
        return len(self._chats[chat_id].queue)

    # ── التشغيل ────────────────────────────────────────────────────────────

    async def play_or_queue(
        self, chat_id: int, song: SongInfo
    ) -> dict:
        """
        شغّل الأغنية فوراً إذا كانت المجموعة فارغة، وإلا أضفها لقائمة الانتظار.

        Returns:
            {"status": "playing" | "queued", "song": SongInfo, "position": int}

        Raises:
            ValueError: إذا امتلأت قائمة الانتظار.
        """
        chat = self._get(chat_id)

        async with chat.lock:
            if chat.is_playing:
                if len(chat.queue) >= MAX_QUEUE_SIZE:
                    raise ValueError(
                        f"قائمة الانتظار ممتلئة ({MAX_QUEUE_SIZE} أغنية). "
                        "استخدم 'تخطي' أو 'إيقاف' أولاً."
                    )
                chat.queue.append(song)
                position = len(chat.queue)
                logger.info(
                    "[%d] إضافة إلى القائمة (#%d): %s", chat_id, position, song.title
                )
                return {"status": "queued", "song": song, "position": position}

            # لا يوجد تشغيل — ابدأ مباشرة
            await self._start_stream(chat_id, chat, song)
            return {"status": "playing", "song": song, "position": 0}

    async def skip(self, chat_id: int) -> dict:
        """
        تخطي الأغنية الحالية.

        Returns:
            {"status": "not_playing" | "stopped" | "skipped", "song": Optional[SongInfo]}
        """
        chat = self._get(chat_id)

        async with chat.stream_lock:
            if not chat.is_playing:
                return {"status": "not_playing", "song": None}

            next_song = await self._advance(chat_id, chat)
            if not next_song:
                return {"status": "stopped", "song": None}
            return {"status": "skipped", "song": next_song}

    async def stop(self, chat_id: int) -> dict:
        """إيقاف التشغيل ومسح قائمة الانتظار."""
        chat = self._get(chat_id)

        async with chat.lock:
            chat.queue.clear()
            chat.current = None
            chat.is_playing = False

        await self._leave_call(chat_id)
        logger.info("[%d] إيقاف التشغيل.", chat_id)
        return {"status": "stopped"}

    # ── معالج انتهاء البث ──────────────────────────────────────────────────

    async def on_stream_end(self, chat_id: int) -> Optional[SongInfo]:
        """
        يُستدعى عند انتهاء الأغنية تلقائياً.
        يستخدم stream_lock لمنع التكرار إذا وصل الحدث مرتين.
        """
        chat = self._get(chat_id)

        # إذا كان stream_lock مشغولاً فهذا تكرار — تجاهله
        if chat.stream_lock.locked():
            return None

        async with chat.stream_lock:
            return await self._advance(chat_id, chat)

    # ── عمليات داخلية ──────────────────────────────────────────────────────

    async def _start_stream(
        self, chat_id: int, chat: ChatPlayer, song: SongInfo, is_change: bool = False
    ) -> None:
        """ابدأ أو غيّر بث الصوت مع منطق Retry."""
        # تحديث الرابط إذا كان على وشك الانتهاء
        song = await self._ensure_fresh_url(song)

        stream = MediaStream(song.url)

        for attempt in range(1, 4):
            try:
                if is_change:
                    await self._calls.change_stream(chat_id, stream)
                else:
                    await self._calls.join_group_call(chat_id, stream)
                break
            except Exception as e:
                logger.warning(
                    "[%d] فشل %s [محاولة %d/3]: %s",
                    chat_id,
                    "change_stream" if is_change else "join_group_call",
                    attempt,
                    e,
                )
                if attempt == 3:
                    raise
                await asyncio.sleep(2 * attempt)

        chat.current = song
        chat.is_playing = True
        logger.info("[%d] يعمل الآن: %s", chat_id, song.title)

    async def _advance(
        self, chat_id: int, chat: ChatPlayer
    ) -> Optional[SongInfo]:
        """انتقل للأغنية التالية أو أوقف التشغيل إذا انتهت القائمة."""
        async with chat.lock:
            if not chat.queue:
                chat.current = None
                chat.is_playing = False

        if not chat.is_playing:
            await self._leave_call(chat_id)
            logger.info("[%d] انتهت القائمة — مغادرة المكالمة.", chat_id)
            return None

        async with chat.lock:
            next_song = chat.queue.popleft()

        try:
            await self._start_stream(chat_id, chat, next_song, is_change=True)
            return next_song
        except Exception as e:
            logger.error(
                "[%d] فشل تشغيل '%s': %s — الانتقال للتالية.", chat_id, next_song.title, e
            )
            # حاول الأغنية التالية بعد ذلك
            return await self._advance(chat_id, chat)

    async def _ensure_fresh_url(self, song: SongInfo) -> SongInfo:
        """تحديث رابط البث إذا كان سينتهي قريباً."""
        # روابط YouTube صالحة لـ 6 ساعات تقريباً
        if not song.is_url_fresh(max_age=21600 - URL_REFRESH_BEFORE_EXPIRY):
            try:
                song = await refresh_url(song)
            except Exception as e:
                logger.warning("فشل تحديث الرابط: %s — استخدام الرابط القديم.", e)
        return song

    async def _leave_call(self, chat_id: int) -> None:
        """مغادرة المكالمة الصوتية بأمان."""
        try:
            await self._calls.leave_group_call(chat_id)
        except Exception as e:
            logger.debug("[%d] مغادرة المكالمة: %s", chat_id, e)

    def cleanup_idle_chats(self, idle_threshold: int = 3600) -> int:
        """إزالة حالات المجموعات الخاملة من الذاكرة لتوفير الموارد."""
        import time
        to_remove = [
            cid
            for cid, chat in self._chats.items()
            if not chat.is_playing and not chat.queue
        ]
        for cid in to_remove:
            del self._chats[cid]
        if to_remove:
            logger.debug("تنظيف حالة %d مجموعة خاملة", len(to_remove))
        return len(to_remove)
