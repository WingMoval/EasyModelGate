"""API Key 管理共享业务服务（CLI 与未来 Admin API 共用）。

- 完整 Key 仅 create_key 生成并返回一次；其余函数只接触哈希与前缀。
- 内部管理操作统一按 key_id；CLI 的 prefix 参数经 resolve_key_prefix
  解析为 key 记录后复用同一套 by-id 操作。
- 不 print、不感知 HTTP；错误以领域异常表达。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..core.security import generate_key, hash_key, mask_key
from ..db import dao
from ..db.database import Database

_KEEP = object()
_CLEAR = object()
KEEP: Any = _KEEP    # 保持当前值
CLEAR: Any = _CLEAR  # 清除限额（置 NULL）


class KeyNotFound(Exception):
    def __init__(self, key_id: int) -> None:
        self.key_id = key_id
        super().__init__(f"key not found: id={key_id}")


class AmbiguousKeyPrefix(Exception):
    """prefix 匹配数 != 1（0=不存在，>1=冲突）。"""

    def __init__(self, prefix: str, count: int) -> None:
        self.prefix = prefix
        self.count = count
        super().__init__(f"prefix {prefix} matched {count} keys (need exactly 1)")


async def create_key(db: Database, *, user_id: int, name: str | None,
                     rpm: int | None, token_limit: int | None,
                     expires_in_days: int | None, timezone: str,
                     key_prefix: str) -> tuple[int, str, str]:
    """返回 (key_id, full_key, masked)。full_key 仅此一次。"""
    expires_ms = None
    if expires_in_days is not None:
        dt = datetime.now(ZoneInfo(timezone)) + timedelta(days=expires_in_days)
        expires_ms = int(dt.timestamp() * 1000)
    full, prefix = generate_key(key_prefix)
    kid = await dao.create_api_key(db, user_id=user_id, name=name,
                                   key_prefix=prefix, key_hash=hash_key(full),
                                   expires_at=expires_ms, rpm_limit=rpm,
                                   token_limit=token_limit)
    return kid, full, mask_key(prefix)


async def get_key(db: Database, key_id: int) -> Any:
    row = await dao.get_key_by_id(db, key_id)
    if row is None:
        raise KeyNotFound(key_id)
    return row


async def list_keys(db: Database, user_id: int | None = None) -> list[Any]:
    return await dao.list_keys(db, user_id)


async def list_keys_with_owner(db: Database) -> list[dict[str, Any]]:
    """Key 列表 + 属主用户名。两次批量查询（keys + users）合成，无 N+1。"""
    rows = await dao.list_keys(db, None)
    names = {int(u["id"]): u["username"] for u in await dao.list_users(db)}
    return [dict(r) | {"username": names.get(int(r["user_id"]))} for r in rows]


async def get_key_with_owner(db: Database, key_id: int) -> dict[str, Any]:
    row = await get_key(db, key_id)
    user = await dao.get_user_by_id(db, int(row["user_id"]))
    return dict(row) | {"username": user["username"] if user else None}


async def resolve_key_prefix(db: Database, prefix: str) -> Any:
    """prefix 唯一匹配（存储的 key_prefix 即完整 Key 前 12 位）。"""
    matches = await dao.find_keys_by_prefix(db, prefix)
    if len(matches) != 1:
        raise AmbiguousKeyPrefix(prefix, len(matches))
    return matches[0]


async def set_key_enabled(db: Database, key_id: int, enabled: bool) -> None:
    if not await dao.set_key_enabled_by_id(db, key_id, enabled):
        raise KeyNotFound(key_id)


async def set_key_limits(db: Database, key_id: int, *,
                         rpm: Any = KEEP, token_limit: Any = KEEP
                         ) -> tuple[int, int | None, int | None]:
    """合并语义：KEEP=保持当前值，CLEAR=置 NULL，数值=直接设置。

    返回 (key_id, new_rpm_limit, new_token_limit)。
    """
    target = await get_key(db, key_id)
    new_rpm = (None if rpm is _CLEAR
               else target["rpm_limit"] if rpm is KEEP else rpm)
    new_tok = (None if token_limit is _CLEAR
               else target["token_limit"] if token_limit is KEEP else token_limit)
    await dao.set_key_limits_by_id(db, key_id, new_rpm, new_tok)
    return key_id, new_rpm, new_tok
