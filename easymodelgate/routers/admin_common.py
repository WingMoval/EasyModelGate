"""Admin 业务路由共享解析工具：统一错误信封，不透出 FastAPI 默认校验格式。"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from pydantic import BaseModel, ValidationError

from ..core.errors import ApiError


async def parse_json_body(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        raise ApiError(400, "Request body must be JSON",
                       err_type="invalid_request_error", code="bad_request")


def parse_body(model: type[BaseModel], payload: Any) -> BaseModel:
    try:
        return model.model_validate(payload)
    except ValidationError as e:
        loc = ".".join(str(p) for p in e.errors()[0].get("loc", ())) or None
        raise ApiError(422, "Request validation failed",
                       err_type="invalid_request_error",
                       code="validation_error", param=loc) from None


def parse_path_id(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(400, "Path id must be an integer",
                       err_type="invalid_request_error",
                       code="invalid_request") from None
    if value < 1:
        raise ApiError(404, f"id {value} not found",
                       err_type="invalid_request_error", code="not_found")
    return value


# ---------- Task 4 共享：查询参数 / 指标映射 / 健康探测 ----------

def parse_query_int(raw: str, *, name: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, f"Query param '{name}' must be an integer",
                       err_type="invalid_request_error",
                       code="invalid_request") from None


def success_rate(success: int, requests: int) -> float:
    """冻结：requests == 0 → 0.0。"""
    return round(success / requests, 4) if requests else 0.0


def metrics_body(total: dict, *, with_max_queue: bool,
                 with_success_rate: bool = True) -> dict:
    """analytics TOTAL 行 → Admin API 指标对象（显式映射，不虚构）。"""
    body = {
        "requests": total["requests"],
        "success": total["success_count"],
        "failed": total["error_count"],
        "prompt_tokens": total["prompt_tokens"],
        "completion_tokens": total["completion_tokens"],
        "total_tokens": total["total_tokens"],
        "cached_tokens": total["cached_tokens"],
        "avg_duration_ms": total["avg_duration_ms"],
        "avg_queue_wait_ms": total["avg_queue_wait_ms"],
        "avg_upstream_ms": total["avg_upstream_duration_ms"],
        "avg_ttft_ms": total["avg_ttft_ms"],
    }
    if with_success_rate:
        body["success_rate"] = success_rate(total["success_count"],
                                            total["requests"])
    if with_max_queue:
        body["max_queue_wait_ms"] = total["max_queue_wait_ms"]
    return body


async def backend_status(app) -> str:
    """真实探测（复用 app 的 upstream client，短超时），不新造 probe；
    永不抛异常：后端坏时 Dashboard 仍要能展示 unhealthy。"""
    upstream = getattr(app.state, "upstream", None)
    if upstream is None:
        return "unhealthy"
    headers = {}
    if upstream.api_key:
        headers["Authorization"] = f"Bearer {upstream.api_key}"
    try:
        resp = await upstream.client.get("/v1/models", headers=headers,
                                         timeout=2.0)
    except Exception:
        return "unhealthy"
    return "healthy" if resp.status_code < 500 else "unhealthy"


async def database_status(app) -> str:
    try:
        cur = await app.state.db.conn.execute("SELECT 1")
        await cur.fetchone()
    except Exception:
        return "unhealthy"
    return "healthy"
