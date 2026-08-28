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


async def set_user_enabled_by_id(db: Database, user_id: int, enabled: bool) -> bool:
    cur = await db.conn.execute(
        "UPDATE users SET enabled=? WHERE id=?", (int(enabled), user_id))
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


async def get_key_by_id(db: Database, key_id: int) -> Any:
    cur = await db.conn.execute("SELECT * FROM api_keys WHERE id=?", (key_id,))
    return await cur.fetchone()


async def set_key_limits_by_id(db: Database, key_id: int,
                               rpm_limit: int | None,
                               token_limit: int | None) -> bool:
    cur = await db.conn.execute(
        "UPDATE api_keys SET rpm_limit=?, token_limit=? WHERE id=?",
        (rpm_limit, token_limit, key_id))
    await db.conn.commit()
    return cur.rowcount > 0


async def touch_last_used(db: Database, key_id: int, ts_ms: int | None = None) -> None:
    await db.conn.execute("UPDATE api_keys SET last_used_at=? WHERE id=?",
                          (ts_ms or now_ms(), key_id))
    await db.conn.commit()


# ---------- settings（通用 KV；value 一律 JSON 文本） ----------

async def get_setting(db: Database, key: str) -> str | None:
    cur = await db.conn.execute(
        "SELECT value_json FROM settings WHERE key=?", (key,))
    row = await cur.fetchone()
    return None if row is None else row["value_json"]


async def set_setting(db: Database, key: str, value_json: str) -> None:
    await db.conn.execute(
        "INSERT INTO settings (key, value_json) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
        (key, value_json))
    await db.conn.commit()


# ---------- request_logs（Dashboard 明细，仅元数据列） ----------

async def list_request_logs(db: Database, *, limit: int = 50,
                            errors_only: bool = False,
                            user_id: int | None = None,
                            api_key_id: int | None = None,
                            model: str | None = None,
                            status_code: int | None = None,
                            error_type: str | None = None) -> list[Any]:
    """最近请求元数据，id DESC 确定性排序；绝不 SELECT 内容列（表内本无内容列，
    client_ip / error_message 亦不外泄）。username/key_name 经 LEFT JOIN 一次取回。"""
    where = ["1=1"]
    params: list = []
    if errors_only:
        where.append("rl.error_type IS NOT NULL")
    for col, val in (("rl.user_id", user_id), ("rl.api_key_id", api_key_id),
                     ("rl.model", model), ("rl.status_code", status_code),
                     ("rl.error_type", error_type)):
        if val is not None:
            where.append(f"{col}=?")
            params.append(val)
    params.append(max(1, min(int(limit), 200)))
    cur = await db.conn.execute(
        f"""SELECT rl.id, rl.request_id, rl.started_at, rl.finished_at,
                   rl.user_id, u.username, rl.api_key_id, k.name AS key_name,
                   k.key_prefix AS key_prefix, rl.model, rl.endpoint,
                   rl.status_code, rl.upstream_status_code, rl.stream,
                   rl.prompt_tokens, rl.completion_tokens, rl.total_tokens,
                   rl.cached_tokens, rl.duration_ms, rl.queue_wait_ms,
                   rl.upstream_duration_ms, rl.ttft_ms, rl.finish_reason,
                   rl.error_type
              FROM request_logs rl
              LEFT JOIN users u ON u.id = rl.user_id
              LEFT JOIN api_keys k ON k.id = rl.api_key_id
             WHERE {' AND '.join(where)}
             ORDER BY rl.id DESC LIMIT ?""", params)
    return list(await cur.fetchall())


async def count_enabled_keys(db: Database) -> int:
    cur = await db.conn.execute(
        "SELECT COUNT(*) FROM api_keys WHERE enabled=1")
    row = await cur.fetchone()
    return int(row[0])
