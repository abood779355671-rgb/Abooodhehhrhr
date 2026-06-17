"""
database.py — إدارة قاعدة البيانات SQLite بشكل آمن ومُحسَّن
- استخدام context manager لضمان إغلاق الاتصالات دائماً
- منع تسريب الاتصالات
- فهارس للاستعلامات السريعة
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    """مدير قاعدة البيانات مع context manager آمن."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = str(db_path)
        self._init_db()

    @contextmanager
    def _conn(self):
        """فتح اتصال SQLite وإغلاقه تلقائياً حتى عند وقوع استثناء."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30,
            check_same_thread=False,
            isolation_level=None,  # autocommit — نتحكم بالمعاملات يدوياً
        )
        conn.execute("PRAGMA journal_mode=WAL")   # أداء أعلى مع الكتابات المتزامنة
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """إنشاء الجداول والفهارس عند التشغيل الأول."""
        with self._conn() as conn:
            conn.executescript("""
                BEGIN;

                CREATE TABLE IF NOT EXISTS groups (
                    chat_id   INTEGER PRIMARY KEY,
                    title     TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS group_admins (
                    chat_id    INTEGER NOT NULL,
                    user_id    INTEGER NOT NULL,
                    name       TEXT,
                    status     TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (chat_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_group_admins_chat
                    ON group_admins (chat_id);

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS banned_groups (
                    chat_id    INTEGER PRIMARY KEY,
                    title      TEXT,
                    reason     TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS play_stats (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id    INTEGER,
                    chat_title TEXT,
                    user_id    INTEGER,
                    user_name  TEXT,
                    query      TEXT,
                    song_title TEXT,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_play_stats_chat
                    ON play_stats (chat_id);
                CREATE INDEX IF NOT EXISTS idx_play_stats_user
                    ON play_stats (user_id);

                COMMIT;
            """)
        logger.info("قاعدة البيانات جاهزة: %s", self.db_path)

    # ── المجموعات ─────────────────────────────────────────────────────────

    def save_group(self, chat_id: int, title: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO groups (chat_id, title, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title      = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (chat_id, title, datetime.utcnow().isoformat()),
            )

    def count_groups(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM groups").fetchone()
        return row[0] if row else 0

    # ── المشرفون ──────────────────────────────────────────────────────────

    def clear_admins(self, chat_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM group_admins WHERE chat_id = ?", (chat_id,))

    def save_admin(
        self, chat_id: int, user_id: int, name: str, status: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO group_admins (chat_id, user_id, name, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    name       = excluded.name,
                    status     = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (chat_id, user_id, name, status, datetime.utcnow().isoformat()),
            )

    def is_saved_admin(self, chat_id: int, user_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM group_admins WHERE chat_id = ? AND user_id = ? LIMIT 1",
                (chat_id, user_id),
            ).fetchone()
        return row is not None

    # ── الإعدادات ─────────────────────────────────────────────────────────

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default

    def is_bot_enabled(self) -> bool:
        return self.get_setting("bot_enabled", "1") == "1"

    def set_bot_enabled(self, enabled: bool) -> None:
        self.set_setting("bot_enabled", "1" if enabled else "0")

    # ── الحظر ─────────────────────────────────────────────────────────────

    def ban_group(self, chat_id: int, title: str, reason: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO banned_groups (chat_id, title, reason, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title      = excluded.title,
                    reason     = excluded.reason,
                    created_at = excluded.created_at
                """,
                (chat_id, title, reason, datetime.utcnow().isoformat()),
            )

    def unban_group(self, chat_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM banned_groups WHERE chat_id = ?", (chat_id,))

    def is_group_banned(self, chat_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM banned_groups WHERE chat_id = ? LIMIT 1",
                (chat_id,),
            ).fetchone()
        return row is not None

    def count_banned_groups(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM banned_groups").fetchone()
        return row[0] if row else 0

    # ── إحصائيات التشغيل ──────────────────────────────────────────────────

    def save_play_stat(
        self,
        chat_id: int,
        chat_title: str,
        user_id: int,
        user_name: str,
        query: str,
        song_title: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO play_stats
                    (chat_id, chat_title, user_id, user_name, query, song_title, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    chat_title,
                    user_id,
                    user_name,
                    query,
                    song_title,
                    datetime.utcnow().isoformat(),
                ),
            )

    def count_total_plays(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM play_stats").fetchone()
        return row[0] if row else 0

    def cleanup_old_stats(self, days: int = 30) -> int:
        """حذف سجلات التشغيل الأقدم من N يوم للحفاظ على حجم قاعدة البيانات."""
        cutoff = datetime.utcnow().isoformat()[:10]  # YYYY-MM-DD
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM play_stats WHERE DATE(created_at) < DATE(?, ?)",
                (cutoff, f"-{days} days"),
            )
            deleted = cur.rowcount
        if deleted:
            logger.info("تنظيف قاعدة البيانات: حُذف %d سجل تشغيل قديم", deleted)
        return deleted
