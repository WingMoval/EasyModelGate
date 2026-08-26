"""Public API 路由（规格 §六）。

已实现：GET /health、GET /v1/models、POST /v1/chat/completions（Phase 4-7）。
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from .. import __version__
from ..core.auth import AuthContext, require_auth
from ..core.errors import ApiError
from ..proxy.headers import build_upstream_headers
from ..proxy.relay import forward_chat

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    # 规格 §50：v0.1 保持简单，不做每次触发上游生成的重量级检查
    return {"status": "ok", "version": __version__}


@router.get("/v1/models")
async def list_models(request: Request, _auth=Depends(require_auth)) -> Response:
    upstream = request.app.state.upstream
    headers = build_upstream_headers(request.headers, upstream.api_key)
    try:
        resp = await upstream.client.get("/v1/models", headers=headers)
    except httpx.TimeoutException:
        raise ApiError(504, "Upstream request timed out", err_type="api_error", code="timeout")
    except httpx.HTTPError:
        raise ApiError(502, "Failed to connect to upstream",
                       err_type="api_error", code="connection_error")
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, auth: AuthContext = Depends(require_auth)):
    return await forward_chat(request, auth)
