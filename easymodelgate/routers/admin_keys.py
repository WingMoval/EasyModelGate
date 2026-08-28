"""API Keys Admin API（挂 admin_protected_router，全程 key_id 操作）。

安全：完整 Key 仅 POST /admin/api/keys 响应出现一次；
AdminKeyResponse 模型显式列字段，key_hash 无出口。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core.errors import ApiError
from ..core.security import mask_key
from ..schemas.admin import (AdminKeyCreateRequest, AdminKeyCreateResponse,
                             AdminKeyListResponse, AdminKeyLimitsRequest,
                             AdminKeyResponse)
from ..services import key_service, user_service
from .admin_common import parse_body, parse_json_body, parse_path_id

router = APIRouter(prefix="/admin/api/keys")


def key_payload(row) -> AdminKeyResponse:
    return AdminKeyResponse(
        id=int(row["id"]), user_id=int(row["user_id"]),
        username=row.get("username"), name=row["name"],
        key_prefix=row["key_prefix"], masked_key=mask_key(row["key_prefix"]),
        enabled=bool(row["enabled"]), rpm=row["rpm_limit"],
        token_used=int(row["token_used"]), token_limit=row["token_limit"],
        expires_at=row["expires_at"], last_used_at=row["last_used_at"])


@router.get("")
async def list_keys(request: Request) -> dict:
    rows = await key_service.list_keys_with_owner(request.app.state.db)
    return AdminKeyListResponse(
        items=[key_payload(r) for r in rows]).model_dump(mode="json")


@router.get("/{key_id}")
async def get_key(request: Request, key_id: str) -> dict:
    kid = parse_path_id(key_id)
    try:
        row = await key_service.get_key_with_owner(request.app.state.db, kid)
    except key_service.KeyNotFound:
        raise ApiError(404, f"Key {kid} not found",
                       err_type="invalid_request_error", code="key_not_found")
    return key_payload(row).model_dump(mode="json")


@router.post("")
async def create_key(request: Request) -> dict:
    body = parse_body(AdminKeyCreateRequest, await parse_json_body(request))
    cfg = request.app.state.cfg
    db = request.app.state.db
    try:
        owner = await user_service.get_user_by_id(db, body.user_id)
    except user_service.UserNotFoundById:
        raise ApiError(404, f"User {body.user_id} not found",
                       err_type="invalid_request_error", code="user_not_found")
    kid, full, _masked = await key_service.create_key(
        db, user_id=body.user_id, name=body.name, rpm=body.rpm,
        token_limit=body.token_limit, expires_in_days=body.expires_in_days,
        timezone=cfg.usage.timezone, key_prefix=cfg.security.key_prefix)
    row = await key_service.get_key_with_owner(db, kid)
    content = AdminKeyCreateResponse(
        key=key_payload(row), api_key=full).model_dump(mode="json")
    return JSONResponse(status_code=201, content=content)


async def _set_enabled(request: Request, key_id_raw: str, enabled: bool) -> dict:
    kid = parse_path_id(key_id_raw)
    db = request.app.state.db
    try:
        await key_service.set_key_enabled(db, kid, enabled)
        row = await key_service.get_key_with_owner(db, kid)
    except key_service.KeyNotFound:
        raise ApiError(404, f"Key {kid} not found",
                       err_type="invalid_request_error", code="key_not_found")
    return key_payload(row).model_dump(mode="json")


@router.post("/{key_id}/enable")
async def enable_key(request: Request, key_id: str) -> dict:
    return await _set_enabled(request, key_id, True)


@router.post("/{key_id}/disable")
async def disable_key(request: Request, key_id: str) -> dict:
    return await _set_enabled(request, key_id, False)


@router.patch("/{key_id}/limits")
async def patch_limits(request: Request, key_id: str) -> dict:
    body = parse_body(AdminKeyLimitsRequest, await parse_json_body(request))
    kid = parse_path_id(key_id)
    db = request.app.state.db
    # 缺失=KEEP，显式 null=CLEAR，整数=SET —— 直接映射 Task 1 合并语义
    rpm = (key_service.KEEP if "rpm" not in body.model_fields_set else
           key_service.CLEAR if body.rpm is None else body.rpm)
    tok = (key_service.KEEP if "token_limit" not in body.model_fields_set else
           key_service.CLEAR if body.token_limit is None else body.token_limit)
    try:
        await key_service.set_key_limits(db, kid, rpm=rpm, token_limit=tok)
        row = await key_service.get_key_with_owner(db, kid)
    except key_service.KeyNotFound:
        raise ApiError(404, f"Key {kid} not found",
                       err_type="invalid_request_error", code="key_not_found")
    return key_payload(row).model_dump(mode="json")
