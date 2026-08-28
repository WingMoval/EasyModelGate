"""用户管理共享业务服务（CLI 与未来 Admin API 共用）。

约束：不 print、不感知 HTTP、不组织终端表格；错误以领域异常表达，
由调用方（CLI → 终端输出 / exit code；Admin API → HTTP envelope）转换。
"""
from __future__ import annotations

from typing import Any

from ..db import dao
from ..db.database import Database


class UserAlreadyExists(Exception):
    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"user already exists: {username}")


class UserNotFound(Exception):
    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"user not found: {username}")


async def get_user(db: Database, username: str) -> Any:
    return await dao.get_user_by_username(db, username)


async def require_user(db: Database, username: str) -> Any:
    user = await dao.get_user_by_username(db, username)
    if user is None:
        raise UserNotFound(username)
    return user


async def create_user(db: Database, username: str,
                      display_name: str | None = None,
                      note: str | None = None) -> int:
    if await dao.get_user_by_username(db, username) is not None:
        raise UserAlreadyExists(username)
    return await dao.create_user(db, username, display_name, note)


async def list_users(db: Database) -> list[Any]:
    return await dao.list_users(db)


async def set_user_enabled(db: Database, username: str, enabled: bool) -> None:
    if not await dao.set_user_enabled(db, username, enabled):
        raise UserNotFound(username)
