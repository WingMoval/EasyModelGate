"""Users Admin API（挂 admin_protected_router，认证/CSRF 由组级依赖提供）。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core.errors import ApiError
from ..schemas.admin import (AdminUserCreateRequest,
                             AdminUserListResponse,
                             AdminUserResponse)
from ..services import user_service
from .admin_common import parse_body, parse_json_body, parse_path_id

router = APIRouter(prefix="/admin/api/users")


def user_payload(row) -> AdminUserResponse:
    return AdminUserResponse(
        id=int(row["id"]), username=row["username"],
        display_name=row["display_name"], note=row["note"],
        enabled=bool(row["enabled"]), created_at=int(row["created_at"]))


@router.get("")
async def list_users(request: Request) -> dict:
    rows = await user_service.list_users(request.app.state.db)
    return AdminUserListResponse(
        items=[user_payload(r) for r in rows]).model_dump(mode="json")


@router.post("")
async def create_user(request: Request) -> dict:
    body = parse_body(AdminUserCreateRequest, await parse_json_body(request))
    db = request.app.state.db
    try:
        uid = await user_service.create_user(
            db, body.username, body.display_name, body.note)
    except user_service.UserAlreadyExists:
        raise ApiError(409, f"User '{body.username}' already exists",
                       err_type="invalid_request_error",
                       code="user_already_exists")
    row = await user_service.get_user_by_id(db, uid)
    return JSONResponse(status_code=201,
                        content=user_payload(row).model_dump(mode="json"))


async def _set_enabled(request: Request, user_id_raw: str, enabled: bool) -> dict:
    user_id = parse_path_id(user_id_raw)
    db = request.app.state.db
    try:
        row = await user_service.set_user_enabled_by_id(db, user_id, enabled)
    except user_service.UserNotFoundById:
        raise ApiError(404, f"User {user_id} not found",
                       err_type="invalid_request_error",
                       code="user_not_found")
    return user_payload(row).model_dump(mode="json")


@router.post("/{user_id}/enable")
async def enable_user(request: Request, user_id: str) -> dict:
    return await _set_enabled(request, user_id, True)


@router.post("/{user_id}/disable")
async def disable_user(request: Request, user_id: str) -> dict:
    return await _set_enabled(request, user_id, False)
