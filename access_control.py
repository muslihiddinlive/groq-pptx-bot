"""
Ruxsat nazorati — whitelist (ruxsat etilganlar ro'yxati) va kunlik foydalanish
limitlarini SQLite orqali boshqaradi.

Tushunchalar:
- ADMIN (config.ADMIN_USER_IDS) — cheksiz foydalanadi, /admin panelga kiradi,
  whitelist'ni boshqaradi. Bazaga yozilmaydi (har doim .env orqali beriladi).
- WHITELIST — oddiy foydalanuvchilar, faqat admin qo'shgandan keyin botdan
  foydalana oladi. Har biriga kunlik limit belgilanadi (None = cheksiz).

DIQQAT (muhim eslatma): bu SQLite fayli lokal diskda saqlanadi. Render'ning
BEPUL rejasida "persistent disk" yo'q — konteyner har safar qayta ishga
tushganda (deploy, restart, uyqudan uyg'onish) fayl NOLDAN boshlanishi mumkin.
Kichik/test loyihalar uchun bu odatda muammo emas, lekin doimiy saqlash kerak
bo'lsa, Render'da pullik "Persistent Disk" qo'shing.
"""
import datetime
import sqlite3
import threading

from config import ADMIN_USER_IDS, DB_PATH

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Dastur ishga tushganda bir marta chaqiriladi — kerakli jadvallarni yaratadi."""
    with _lock, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whitelist (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                daily_limit INTEGER,   -- NULL = cheksiz
                added_at    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage (
                user_id INTEGER,
                day     TEXT,
                count   INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, day)
            )
        """)
        conn.commit()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS


def is_whitelisted(user_id: int) -> bool:
    """Admin yoki whitelist'da bo'lsa True."""
    if is_admin(user_id):
        return True
    with _lock, _connect() as conn:
        row = conn.execute("SELECT 1 FROM whitelist WHERE user_id = ?", (user_id,)).fetchone()
        return row is not None


def add_user(user_id: int, daily_limit, username: str = "") -> None:
    """
    :param daily_limit: butun son (masalan 5) yoki None (cheksiz).
                         Agar foydalanuvchi allaqachon mavjud bo'lsa, yangilanadi.
    """
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO whitelist (user_id, username, daily_limit, added_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                daily_limit = excluded.daily_limit,
                username = CASE WHEN excluded.username != '' THEN excluded.username ELSE whitelist.username END
            """,
            (user_id, username, daily_limit, datetime.datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()


def remove_user(user_id: int) -> bool:
    """True — o'chirildi, False — ro'yxatda umuman bo'lmagan."""
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM whitelist WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0


def list_users() -> list[tuple]:
    """[(user_id, username, daily_limit, added_at, today_used), ...] qaytaradi."""
    today = datetime.date.today().isoformat()
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, username, daily_limit, added_at FROM whitelist ORDER BY added_at"
        ).fetchall()
        result = []
        for user_id, username, daily_limit, added_at in rows:
            used_row = conn.execute(
                "SELECT count FROM usage WHERE user_id = ? AND day = ?", (user_id, today)
            ).fetchone()
            used = used_row[0] if used_row else 0
            result.append((user_id, username, daily_limit, added_at, used))
        return result


def check_and_increment(user_id: int):
    """
    Foydalanuvchi yangi generatsiya (prezentatsiya/diagramma) so'raganda chaqiriladi.

    :return: (allowed: bool, used: int, limit: int|None)
             limit=None -> cheksiz. allowed=False bo'lsa, usage OSHIRILMAYDI.
    """
    today = datetime.date.today().isoformat()

    if is_admin(user_id):
        with _lock, _connect() as conn:
            conn.execute(
                """
                INSERT INTO usage (user_id, day, count) VALUES (?, ?, 1)
                ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1
                """,
                (user_id, today),
            )
            conn.commit()
        return True, None, None  # admin -> cheksiz

    with _lock, _connect() as conn:
        row = conn.execute("SELECT daily_limit FROM whitelist WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return False, 0, 0  # whitelist'da yo'q

        daily_limit = row[0]
        used_row = conn.execute(
            "SELECT count FROM usage WHERE user_id = ? AND day = ?", (user_id, today)
        ).fetchone()
        used = used_row[0] if used_row else 0

        if daily_limit is not None and used >= daily_limit:
            return False, used, daily_limit

        conn.execute(
            """
            INSERT INTO usage (user_id, day, count) VALUES (?, ?, 1)
            ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1
            """,
            (user_id, today),
        )
        conn.commit()
        return True, used + 1, daily_limit
