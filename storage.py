"""
Хранилище правил доступа "тема -> кто может писать".

Логика:
- у каждой темы (topic_id) в каждой группе (chat_id) есть режим:
    'open'      - писать может любой участник группы (по умолчанию)
    'whitelist' - писать могут только пользователи из allowed_users
- General (общий чат без темы) хранится под topic_id = 0
"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

# На bothost.ru папка /app/data сохраняется между обновлениями и перезапусками
# контейнера (обычный код проекта - нет). Поэтому путь к базе берём из
# переменной окружения DB_PATH, а если её не задали (например, при локальном
# запуске) - используем файл рядом со скриптом.
DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).parent / "bot_data.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topic_rules (
                chat_id INTEGER NOT NULL,
                topic_id INTEGER NOT NULL,
                mode TEXT NOT NULL DEFAULT 'open',
                PRIMARY KEY (chat_id, topic_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS allowed_users (
                chat_id INTEGER NOT NULL,
                topic_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                PRIMARY KEY (chat_id, topic_id, user_id)
            )
            """
        )
        conn.commit()


def get_topic_mode(chat_id: int, topic_id: int) -> str:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT mode FROM topic_rules WHERE chat_id=? AND topic_id=?",
            (chat_id, topic_id),
        ).fetchone()
        return row[0] if row else "open"


def allow_user(chat_id: int, topic_id: int, user_id: int, username: str | None = None) -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            INSERT INTO topic_rules (chat_id, topic_id, mode) VALUES (?, ?, 'whitelist')
            ON CONFLICT(chat_id, topic_id) DO UPDATE SET mode='whitelist'
            """,
            (chat_id, topic_id),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO allowed_users (chat_id, topic_id, user_id, username)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, topic_id, user_id, username),
        )
        conn.commit()


def disallow_user(chat_id: int, topic_id: int, user_id: int) -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "DELETE FROM allowed_users WHERE chat_id=? AND topic_id=? AND user_id=?",
            (chat_id, topic_id, user_id),
        )
        conn.commit()


def is_user_allowed(chat_id: int, topic_id: int, user_id: int) -> bool:
    mode = get_topic_mode(chat_id, topic_id)
    if mode != "whitelist":
        return True
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT 1 FROM allowed_users WHERE chat_id=? AND topic_id=? AND user_id=?",
            (chat_id, topic_id, user_id),
        ).fetchone()
        return row is not None


def list_allowed(chat_id: int, topic_id: int):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute(
            "SELECT user_id, username FROM allowed_users WHERE chat_id=? AND topic_id=?",
            (chat_id, topic_id),
        ).fetchall()


def list_all_rules(chat_id: int):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute(
            "SELECT topic_id, mode FROM topic_rules WHERE chat_id=?",
            (chat_id,),
        ).fetchall()


def reset_topic(chat_id: int, topic_id: int) -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("DELETE FROM allowed_users WHERE chat_id=? AND topic_id=?", (chat_id, topic_id))
        conn.execute("DELETE FROM topic_rules WHERE chat_id=? AND topic_id=?", (chat_id, topic_id))
        conn.commit()
