"""Usage Admin API：summary / timeseries。

时间解析全部走 usage_service.resolve_time_range（与 CLI 同一真相）；
聚合全部走 analytics.summary（唯一 SQL 聚合来源，无第二套）。
过滤按 user_id / key_id（内部 ID 一等标识），不使用 username/prefix。
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.errors import ApiError
from ..services import key_service, usage_service, user_service
from ..services.analytics import SummaryFilter
from .admin_common import (metrics_body, parse_query_int)

router = APIRouter(prefix="/admin/api/usage")

GROUP_BY_CHOICES = ("hour", "day", "week", "month", "none")


async def _parse_usage_params(request: Request):
    """返回 (start_ms, end_ms, default_gb, tz, user_id, key_id, model)。

    时间语义与 CLI 冻结一致：from/to 存在则优先于 period；
    过滤按 user_id / key_id 存在性校验（404）。
    """
    p = request.query_params
    tz = request.app.state.cfg.usage.timezone
    period = p.get("period")
    if period is not None and period not in usage_service.PERIOD_DEFAULT_GROUP:
        raise ApiError(400, f"Unknown period '{period}'",
                       err_type="invalid_request_error", code="invalid_period")
    from_s, to_s = p.get("from"), p.get("to")
    try:
        start_ms, end_ms, default_gb = usage_service.resolve_time_range(
            period, from_s, to_s, tz)
    except ValueError:
        raise ApiError(400, "Invalid from/to time range",
                       err_type="invalid_request_error",
                       code="invalid_time_range") from None
    if (from_s or to_s) and start_ms is not None and end_ms is not None \
            and start_ms >= end_ms:
        raise ApiError(400, "Field 'from' must be earlier than 'to'",
                       err_type="invalid_request_error",
                       code="invalid_time_range")
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
    return start_ms, end_ms, default_gb, tz, user_id, key_id, p.get("model")


def _group_by(request: Request, default_gb: str, param: str = "group_by") -> str:
    gb = request.query_params.get(param)
    if gb is None:
        return default_gb
    if gb not in GROUP_BY_CHOICES:
        raise ApiError(400, f"Unknown group_by '{gb}'",
                       err_type="invalid_request_error",
                       code="invalid_group_by")
    return gb


async def _usage_rows(request: Request, start_ms, end_ms, tz, user_id,
                      key_id, model, granularity):
    f = SummaryFilter(start_ms=start_ms, end_ms=end_ms, user_id=user_id,
                      api_key_id=key_id, model=model, granularity=granularity,
                      timezone=tz)
    return await usage_service.summarize(request.app.state.db, f)


@router.get("/summary")
async def usage_summary(request: Request) -> dict:
    start_ms, end_ms, _gb, tz, user_id, key_id, model = await _parse_usage_params(request)
    rows = await _usage_rows(request, start_ms, end_ms, tz, user_id, key_id,
                             model, None)
    total = rows[-1]
    return {
        "range": {"from_ms": start_ms, "to_ms": end_ms, "timezone": tz},
        "filters": {"user_id": user_id, "key_id": key_id, "model": model},
        "summary": metrics_body(total, with_max_queue=True),
    }


@router.get("/timeseries")
async def usage_timeseries(request: Request) -> dict:
    start_ms, end_ms, default_gb, tz, user_id, key_id, model = await _parse_usage_params(request)
    gb = _group_by(request, default_gb)
    rows = await _usage_rows(request, start_ms, end_ms, tz, user_id, key_id,
                             model, None if gb == "none" else gb)
    if gb == "none":
        items = rows          # analytics 自然行为：仅 TOTAL 单桶
    else:
        items = rows[:-1]     # 去掉 TOTAL 行，仅保留时间桶
    return {
        "group_by": gb,
        "items": [{"bucket": r["bucket"],
                   **metrics_body(r, with_max_queue=False,
                                  with_success_rate=False)}
                  for r in items],
    }
