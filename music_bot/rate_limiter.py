"""
rate_limiter.py — حماية من الفيضانات والإساءة
- Rate Limiting لكل مستخدم ولكل مجموعة
- Anti-Flood
- تتبع الطلبات في نافذة زمنية
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from .config import MAX_REQUESTS_PER_WINDOW, RATE_LIMIT_PLAY, RATE_LIMIT_WINDOW

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate Limiter مزدوج:
    1. حد أدنى للفاصل بين الطلبات (cooldown لكل مستخدم).
    2. حد أقصى للطلبات في نافذة زمنية (لكل مستخدم في كل مجموعة).
    """

    def __init__(self) -> None:
        # آخر توقيت طلب لكل (chat_id, user_id)
        self._last_request: Dict[Tuple[int, int], float] = {}
        # تاريخ الطلبات لكل (chat_id, user_id) في نافذة زمنية
        self._history: Dict[Tuple[int, int], Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(
        self,
        chat_id: int,
        user_id: int,
        cooldown: int = RATE_LIMIT_PLAY,
        window: int = RATE_LIMIT_WINDOW,
        max_req: int = MAX_REQUESTS_PER_WINDOW,
    ) -> Tuple[bool, str]:
        """
        تحقق مما إذا كان المستخدم مسموحاً له بإرسال الطلب الآن.

        Returns:
            (True, "") إذا كان مسموحاً.
            (False, سبب الرفض) إذا كان محدوداً.
        """
        key = (chat_id, user_id)
        now = time.monotonic()

        async with self._lock:
            # ── فحص Cooldown ───────────────────────────────────────────────
            last = self._last_request.get(key, 0.0)
            elapsed = now - last
            if elapsed < cooldown:
                remaining = int(cooldown - elapsed) + 1
                return False, f"انتظر {remaining} ثانية قبل الطلب التالي."

            # ── فحص نافذة الطلبات ─────────────────────────────────────────
            history = self._history[key]
            # أزل الطلبات القديمة خارج النافذة
            while history and now - history[0] > window:
                history.popleft()

            if len(history) >= max_req:
                oldest = history[0]
                wait = int(window - (now - oldest)) + 1
                return False, f"لقد تجاوزت الحد المسموح ({max_req} طلبات/{window}ث). انتظر {wait} ثانية."

            # ── سجّل الطلب ─────────────────────────────────────────────────
            self._last_request[key] = now
            history.append(now)
            return True, ""

    def reset_user(self, chat_id: int, user_id: int) -> None:
        """إعادة ضبط حد المستخدم (للمشرفين)."""
        key = (chat_id, user_id)
        self._last_request.pop(key, None)
        self._history.pop(key, None)

    async def cleanup(self) -> None:
        """حذف الإدخالات المنتهية الصلاحية من الذاكرة."""
        now = time.monotonic()
        async with self._lock:
            stale_keys = [
                k for k, t in self._last_request.items()
                if now - t > RATE_LIMIT_WINDOW * 2
            ]
            for k in stale_keys:
                self._last_request.pop(k, None)
                self._history.pop(k, None)
        if stale_keys:
            logger.debug("Rate limiter: تنظيف %d إدخال منتهي", len(stale_keys))


# نسخة مشتركة واحدة للتطبيق كله
rate_limiter = RateLimiter()
