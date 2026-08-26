"""users / api_keys 数据访问对象（v0.1 仅服务端与 CLI 内部使用）。"""
from __future__ import annotations

import time
from typing import Any

from .database import Database


def now_ms() -> int:
    return int(time.time() * 1000)


# ---------- users ----------

async def create_user(db: Database, username: str, display_name: str | None = None,
                      note: str | None = None, enabled: bool = True) -> int:
    cur = await db.conn.execute(
        "INSERT INTO users (username, display_name, enabled, created_at, note) VALUES (?,?,?,?,?)",
        (username, display_name, int(enabled), now_ms(), note))
    await db.conn.commit()
    return int(cur.lastrowid)


async def get_user_by_username(db: Database, username: str) -> Any:
    cur = await db.conn.execute("SELECT * FROM users WHERE username=?", (username,))
    return await cur.fetchone()


async def get_user_by_id(db: Database, user_id: int) -> Any:
    cur = await db.conn.execute("SELECT * FROM users WHERE id=?", (user_id,))
    return await cur.fetchone()


async def list_users(db: Database) -> list[Any]:
    cur = await db.conn.execute("SELECT * FROM users ORDER BY id")
    return list(await cur.fetchall())


async def set_user_enabled(db: Database, username: str, enabled: bool) -> bool:
    cur = await db.conn.execute(
        "UPDATE users SET enabled=? WHERE username=?", (int(enabled), username))
    await db.conn.commit()
    return cur.rowcount > 0


# ---------- api_keys ----------

async def create_api_key(db: Database, *, user_id: int, name: str | None,
                         key_prefix: str, key_hash: str, expires_at: int | None = None,
                         rpm_limit: int | None = None,
                         token_limit: int | None = None) -> int:
    cur = await db.conn.execute(
        """INSERT INTO api_keys
             (user_id, name, key_prefix, key_hash, enabled, expires_at,
              rpm_limit, token_limit, token_used, created_at, last_used_at)
           VALUES (?,?,?,?,1,?,?,?,?,?,NULL)""",
        (user_id, name, key_prefix, key_hash, expires_at, rpm_limit, token_limit, 0, now_ms()))
    await db.conn.commit()
    return int(cur.lastrowid)


async def get_key_by_hash(db: Database, key_hash: str) -> Any:
    cur = await db.conn.execute("SELECT * FROM api_keys WHERE key_hash=?", (key_hash,))
    return await cur.fetchone()


async def find_keys_by_prefix(db: Database, key_prefix: str) -> list[Any]:
    """前缀精确匹配（存储的 key_prefix 本身就是完整 Key 的前 12 位）。"""
    cur = await db.conn.execute(
        "SELECT * FROM api_keys WHERE key_prefix=? ORDER BY id", (key_prefix,))
    return list(await cur.fetchall())


async def list_keys(db: Database, user_id: int | None = None) -> list[Any]:
    if user_id is None:
        cur = await db.conn.execute("SELECT * FROM api_keys ORDER BY id")
    else:
        cur = await db.conn.execute(
            "SELECT * FROM api_keys WHERE user_id=? ORDER BY id", (user_id,))
    return list(await cur.fetchall())


async def set_key_enabled_by_id(db: Database, key_id: int, enabled: bool) -> bool:
    cur = await db.conn.execute(
        "UPDATE api_keys SET enabled=? WHERE id=?", (int(enabled), key_id))
    await db.conn.commit()
    return cur.rowcount > 0


async def touch_last_used(db: Database, key_id: int, ts_ms: int | None = None) -> None:
    await db.conn.execute("UPDATE api_keys SET last_used_at=? WHERE id=?",
                          (ts_ms or now_ms(), key_id))
    await db.conn.commit()
