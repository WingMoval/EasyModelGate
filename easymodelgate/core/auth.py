"""Bearer API Key 鉴权依赖（规格 §20 / §39）。

验证链：Authorization Bearer → 前缀检查 → SHA-256 → 数据库等值查询
       → enabled / expires_at / user.enabled 检查。
RPM 与软额度在 Phase 11 接入本依赖。
last_used_at 更新以 detached task 执行（规格 §36），不受请求取消影响。
"""
from __future__ import annotations

import dataclasses
import logging

from fastapi import Request

logger = logging.getLogger("easymodelgate.auth")

from ..db import dao
from ..core.errors import ApiError
from ..core.security import hash_key, mask_key


@dataclasses.dataclass(frozen=True)
class AuthContext:
    user_id: int
    api_key_id: int
    username: str
    masked_key: str
    rpm_limit: int | None = None
    token_limit: int | None = None
    token_used: int | None = None


async def require_auth(request: Request) -> AuthContext:
    logger.debug("auth begin")
    cfg = request.app.state.cfg
    db = request.app.state.db

    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "Missing API key", code="invalid_api_key")
    if not token.startswith(cfg.security.key_prefix):
        raise ApiError(401, "Invalid API key", code="invalid_api_key")

    row = await dao.get_key_by_hash(db, hash_key(token))
    logger.debug("auth looked up key row=%s", row is not None)
    if row is None:
        raise ApiError(401, "Invalid API key", code="invalid_api_key")

    now = dao.now_ms()
    if not row["enabled"]:
        raise ApiError(401, "API key has been disabled", code="key_disabled")
    if row["expires_at"] is not None and row["expires_at"] <= now:
        raise ApiError(401, "API key has expired", code="key_expired")

    user = await dao.get_user_by_id(db, int(row["user_id"]))
    if user is None or not user["enabled"]:
        raise ApiError(403, "User account is disabled", code="user_disabled")

    request.state.auth = AuthContext(
        user_id=int(row["user_id"]),
        api_key_id=int(row["id"]),
        username=user["username"],
        masked_key=mask_key(row["key_prefix"]),
        rpm_limit=row["rpm_limit"],
        token_limit=row["token_limit"],
        token_used=row["token_used"],
    )
    request.app.state.spawn(dao.touch_last_used(db, int(row["id"])))
    return request.state.auth
