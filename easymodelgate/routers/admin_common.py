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
