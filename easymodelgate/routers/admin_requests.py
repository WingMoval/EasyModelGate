"""Recent Requests Admin API（明细元数据；绝不返回内容/敏感列）。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.errors import ApiError
from ..core.security import mask_key
from ..db import dao
from ..services import key_service, user_service
from .admin_common import parse_query_int

router = APIRouter(prefix="/admin/api")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _parse_bool(raw: str | None) -> bool:
    return (raw or "").lower() in ("1", "true", "yes")


@router.get("/requests")
async def recent_requests(request: Request) -> dict:
    p = request.query_params
    limit_raw = p.get("limit")
    limit = DEFAULT_LIMIT
    if limit_raw is not None:
        limit = parse_query_int(limit_raw, name="limit")
        if not 1 <= limit <= MAX_LIMIT:
            raise ApiError(400, f"limit must be between 1 and {MAX_LIMIT}",
                           err_type="invalid_request_error",
                           code="invalid_limit")
    db = request.app.state.db
    user_id = key_id = None
    if p.get("user_id") is not None:
        uid = parse_query_int(p["user_id"], name="user_id")
        try:
            await user_service.get_user_by_id(db, uid)
        except user_service.UserNotFoundById:
            raise ApiError(404, f"User {uid} not found",
                           err_type="invalid_request_error",
                           code="user_not_found") from None
        user_id = uid
    if p.get("key_id") is not None:
        kid = parse_query_int(p["key_id"], name="key_id")
        try:
            await key_service.get_key(db, kid)
        except key_service.KeyNotFound:
            raise ApiError(404, f"Key {kid} not found",
                           err_type="invalid_request_error",
                           code="key_not_found") from None
        key_id = kid
    status_code = None
    if p.get("status_code") is not None:
        status_code = parse_query_int(p["status_code"], name="status_code")
    rows = await dao.list_request_logs(
        db, limit=limit, errors_only=_parse_bool(p.get("errors_only")),
        user_id=user_id, api_key_id=key_id, model=p.get("model"),
        status_code=status_code, error_type=p.get("error_type"))
    items = []
    for r in rows:
        d = dict(r)
        d["stream"] = None if d["stream"] is None else bool(d["stream"])
        prefix = d.pop("key_prefix")
        d["masked_key"] = mask_key(prefix) if prefix else None
        items.append(d)
    return {"items": items}
