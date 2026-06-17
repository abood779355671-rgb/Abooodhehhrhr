"""
youtube.py — استخراج روابط البث من YouTube باستخدام yt-dlp
- منطق Retry تلقائي
- تحديث الروابط المنتهية الصلاحية
- دعم الروابط المباشرة والبحث النصي
"""

import asyncio
import logging
import time
from typing import Optional

import yt_dlp

from .config import MAX_SONG_DURATION, YTDLP_RETRIES

logger = logging.getLogger(__name__)

# خيارات yt-dlp الأساسية
_BASE_OPTS: dict = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "default_search": "ytsearch1",
    "extract_flat": False,
    "socket_timeout": 30,
    "retries": 3,
    "source_address": "0.0.0.0",
    "geo_bypass": True,
}


class SongInfo:
    """بيانات الأغنية المستخرجة من yt-dlp."""

    __slots__ = (
        "title",
        "url",
        "webpage_url",
        "duration",
        "thumbnail",
        "extracted_at",
    )

    def __init__(
        self,
        title: str,
        url: str,
        webpage_url: str,
        duration: Optional[int],
        thumbnail: Optional[str],
    ) -> None:
        self.title = title
        self.url = url
        self.webpage_url = webpage_url
        self.duration = duration
        self.thumbnail = thumbnail
        self.extracted_at: float = time.monotonic()

    def is_url_fresh(self, max_age: int = 18000) -> bool:
        """هل الرابط المباشر لا يزال طازجاً؟ (روابط YouTube تنتهي بعد ~6 ساعات)."""
        return (time.monotonic() - self.extracted_at) < max_age

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "webpage_url": self.webpage_url,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "extracted_at": self.extracted_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SongInfo":
        obj = cls(
            title=data["title"],
            url=data["url"],
            webpage_url=data["webpage_url"],
            duration=data.get("duration"),
            thumbnail=data.get("thumbnail"),
        )
        obj.extracted_at = data.get("extracted_at", time.monotonic())
        return obj

    def __repr__(self) -> str:
        mins = self.duration // 60 if self.duration else 0
        secs = self.duration % 60 if self.duration else 0
        return f"<SongInfo title={self.title!r} duration={mins}:{secs:02d}>"


def _extract_sync(query: str, is_refresh: bool = False) -> dict:
    """استدعاء yt-dlp بشكل متزامن (يُستدعى داخل thread منفصل)."""
    opts = dict(_BASE_OPTS)

    # عند التحديث نعرف URL المصدر مسبقاً
    if is_refresh:
        opts.pop("default_search", None)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)

    # البحث يُرجع قائمة entries
    if info and "entries" in info:
        info = info["entries"][0]

    if not info:
        raise ValueError("لم يتم العثور على نتائج لـ: " + query)

    return {
        "title": info.get("title", "أغنية غير معروفة"),
        "url": info.get("url") or info.get("manifest_url"),
        "webpage_url": info.get("webpage_url", query),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
    }


async def search_audio(query: str) -> SongInfo:
    """
    ابحث عن أغنية أو استخرج رابط URL مباشر مع منطق Retry.

    Args:
        query: اسم الأغنية أو رابط YouTube المباشر.

    Returns:
        SongInfo مع رابط البث المباشر.

    Raises:
        RuntimeError: إذا فشلت جميع محاولات الاستخراج.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, YTDLP_RETRIES + 1):
        try:
            logger.debug("استخراج yt-dlp [محاولة %d/%d]: %s", attempt, YTDLP_RETRIES, query)
            data = await asyncio.to_thread(_extract_sync, query, False)

            if not data.get("url"):
                raise ValueError("yt-dlp أرجع رابطاً فارغاً")

            # التحقق من مدة الأغنية
            if data["duration"] and data["duration"] > MAX_SONG_DURATION:
                raise ValueError(
                    f"الأغنية أطول من الحد المسموح به "
                    f"({data['duration'] // 60} دقيقة > {MAX_SONG_DURATION // 60} دقيقة)"
                )

            song = SongInfo(**data)
            logger.info("تم استخراج: %s", song)
            return song

        except yt_dlp.utils.DownloadError as e:
            last_error = e
            logger.warning("yt-dlp DownloadError [محاولة %d]: %s", attempt, e)
        except Exception as e:
            last_error = e
            logger.warning("خطأ yt-dlp [محاولة %d]: %s", attempt, e)

        if attempt < YTDLP_RETRIES:
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

    raise RuntimeError(
        f"فشل استخراج الصوت بعد {YTDLP_RETRIES} محاولات: {last_error}"
    )


async def refresh_url(song: SongInfo) -> SongInfo:
    """
    تحديث رابط البث المباشر لأغنية موجودة (عند انتهاء صلاحية الرابط).

    Args:
        song: SongInfo الأصلية.

    Returns:
        SongInfo جديدة برابط محدث.
    """
    logger.info("تحديث رابط انتهت صلاحيته: %s", song.title)
    try:
        data = await asyncio.to_thread(_extract_sync, song.webpage_url, True)
        if not data.get("url"):
            raise ValueError("رابط مُحدَّث فارغ")
        refreshed = SongInfo(**data)
        logger.info("تم تحديث الرابط: %s", refreshed.title)
        return refreshed
    except Exception as e:
        logger.error("فشل تحديث الرابط لـ %s: %s", song.title, e)
        raise
