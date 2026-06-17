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
from pytgcalls.types.input_stream import AudioImagePiped

from .config import MAX_QUEUE_SIZE, URL_REFRESH_BEFORE_EXPIRY
from .youtube import SongInfo, refresh_url

logger = logging.getLogger(__name__)


class ChatPlayer:
    __slots__ = ("queue", "current", "is_playing", "lock", "stream_lock")

    def __init__(self) -> None:
        self.queue: deque[SongInfo] = deque()
        self.current: Optional[SongInfo] = None
        self.is_playing: bool = False
        self.lock = asyncio.Lock()
        self.stream_lock = asyncio.Lock()


class MusicPlayer:
    def __init__(self, calls: PyTgCalls) -> None:
        self._calls = calls
        self._chats: Dict[int, ChatPlayer] = defaultdict(ChatPlayer)

    def _get(self, chat_id: int) -> ChatPlayer:
        return self._chats[chat_id]

    # ── API ─────────────────────────────────────────────

    def is_playing(self, chat_id: int) -> bool:
        return self._chats[chat_id].is_playing

    def get_current(self, chat_id: int) -> Optional[SongInfo]:
        return self._chats[chat_id].current

    def get_queue(self, chat_id: int) -> list[SongInfo]:
        return list(self._chats[chat_id].queue)

    def queue_size(self, chat_id: int) -> int:
        return len(self._chats[chat_id].queue)

    # ── تشغيل / إضافة ──────────────────────────────────

    async def play_or_queue(self, chat_id: int, song: SongInfo) -> dict:
        chat = self._get(chat_id)

        async with chat.lock:
            if chat.is_playing:
                if len(chat.queue) >= MAX_QUEUE_SIZE:
                    raise ValueError("قائمة الانتظار ممتلئة.")

                chat.queue.append(song)
                return {
                    "status": "queued",
                    "song": song,
                    "position": len(chat.queue),
                }

            await self._start_stream(chat_id, chat, song)
            return {"status": "playing", "song": song, "position": 0}

    async def skip(self, chat_id: int) -> dict:
        chat = self._get(chat_id)

        async with chat.stream_lock:
            if not chat.is_playing:
                return {"status": "not_playing", "song": None}

            next_song = await self._advance(chat_id, chat)
            if not next_song:
                return {"status": "stopped", "song": None}

            return {"status": "skipped", "song": next_song}

    async def stop(self, chat_id: int) -> dict:
        chat = self._get(chat_id)

        async with chat.lock:
            chat.queue.clear()
            chat.current = None
            chat.is_playing = False

        await self._leave_call(chat_id)
        return {"status": "stopped"}

    # ── Stream End ──────────────────────────────────────

    async def on_stream_end(self, chat_id: int):
        chat = self._get(chat_id)

        if chat.stream_lock.locked():
            return None

        async with chat.stream_lock:
            return await self._advance(chat_id, chat)

    # ── Core ─────────────────────────────────────────────

    async def _start_stream(self, chat_id, chat, song, is_change=False):
        song = await self._ensure_fresh_url(song)

        stream = AudioImagePiped(song.url)

        for attempt in range(3):
            try:
                if is_change:
                    await self._calls.change_stream(chat_id, stream)
                else:
                    await self._calls.join_group_call(chat_id, stream)
                break
            except Exception as e:
                logger.warning("[%s] retry %s", chat_id, e)
                if attempt == 2:
                    raise
                await asyncio.sleep(2 * (attempt + 1))

        chat.current = song
        chat.is_playing = True

    async def _advance(self, chat_id, chat):
        async with chat.lock:
            if not chat.queue:
                chat.is_playing = False
                chat.current = None

        if not chat.is_playing:
            await self._leave_call(chat_id)
            return None

        async with chat.lock:
            next_song = chat.queue.popleft()

        try:
            await self._start_stream(chat_id, chat, next_song, True)
            return next_song
        except Exception:
            return await self._advance(chat_id, chat)

    async def _ensure_fresh_url(self, song: SongInfo):
        if not song.is_url_fresh(max_age=21600 - URL_REFRESH_BEFORE_EXPIRY):
            try:
                return await refresh_url(song)
            except Exception:
                return song
        return song

    async def _leave_call(self, chat_id: int):
        try:
            await self._calls.leave_group_call(chat_id)
        except Exception:
            pass
