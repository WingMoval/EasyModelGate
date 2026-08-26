"""chat/completions 透明代理转发（Phase 4-11 核心，ADR-0004）。

原则：
- dict body + 最小校验（规格 §11）；除 usage 注入外不改请求
- 流式：aiter_bytes() 原始字节直接 yield + 同一份副本喂 SseScanner
- 非流式：透传上游 status/body；旁路解析 usage/finish_reason
- 断连：try/except CancelledError/finally aclose（EXP-04 模式）
- 日志：detached task 落库；不保存 prompt/response 内容

Phase 8-11：
- 鉴权 → RPM → Token 软额度 → Semaphore 排队 → Upstream（拒绝请求不占 GPU 位）
- queue_wait_ms 以 monotonic 计算；queue 超时 503 server_busy
- total_request_timeout 覆盖 排队+upstream+streaming 全生命周期
- token_used 与 request_logs 在同一事务内原子累加（仅当 usage 可靠）
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from ..core.auth import AuthContext
from ..core.concurrency import SlotQueueTimeout
from ..core.errors import ApiError
from ..db import dao
from ..services.request_logging import persist_request_log
from .headers import build_upstream_headers
from .sse import SseScanner

logger = logging.getLogger("easymodelgate.relay")

STREAM_RESPONSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _validate_body(body) -> None:
    """规格 §11：最低限度校验，未知字段一律保留。"""
    if not isinstance(body, dict):
        raise ApiError(400, "Request body must be a JSON object", code="invalid_request_body")
    messages = body.get("messages")
    if (not isinstance(messages, list) or not messages
            or not all(isinstance(m, dict) for m in messages)):
        raise ApiError(400, "'messages' must be a non-empty array of objects",
                       code="invalid_messages")
    if "model" in body and not isinstance(body["model"], str):
        raise ApiError(400, "'model' must be a string", code="invalid_model")


def maybe_inject_usage(body: dict) -> tuple[dict, bool]:
    """规格 §12：仅当 stream=true 且 stream_options 整体缺失时注入
    {"include_usage": true}；客户端已提供该对象则原样保留（含 false）。"""
    if body.get("stream") is True and "stream_options" not in body:
        return {**body, "stream_options": {"include_usage": True}}, True
    return body, False


def _enforce_limits(request: Request, auth: AuthContext, body: dict,
                    raw_input_bytes: int, stream: bool, t0: float) -> None:
    """Phase 11：RPM 与 Token 软额度检查。

    必须发生在 Semaphore 之前（被拒请求不得占 GPU 排队位）；
    拒绝同样写 request_logs：status_code=429、queue_wait_ms=0。
    """
    app = request.app
    limit_err: tuple[str, int, str, str, int | None] | None = None
    retry_after: int | None = None

    allowed, retry_after = app.state.limiter.check(auth.api_key_id, auth.rpm_limit)
    if not allowed:
        limit_err = ("rate_limited", "rate_limit_error", "rate_limit_exceeded",
                     f"Rate limit exceeded for this key "
                     f"({auth.rpm_limit} requests per minute).", retry_after)
    elif (auth.token_limit is not None
          and (auth.token_used or 0) >= auth.token_limit):
        limit_err = ("quota_exceeded", "insufficient_quota", "insufficient_quota",
                     f"Token quota exceeded: used {auth.token_used} >= "
                     f"limit {auth.token_limit}. This request was rejected.", None)

    if limit_err is None:
        return

    err_type, env_type, code, message, retry_after = limit_err
    now = dao.now_ms()
    app.state.spawn(persist_request_log(app.state.db, {
        "request_id": uuid.uuid4().hex,
        "user_id": auth.user_id,
        "api_key_id": auth.api_key_id,
        "backend_id": getattr(app.state, "backend_id", None),
        "model": body.get("model"),
        "endpoint": "/v1/chat/completions",
        "started_at": now,
        "finished_at": now,
        "duration_ms": int((time.monotonic() - t0) * 1000),
        "queue_wait_ms": 0,           # 未进入排队
        "stream": int(stream),
        "status_code": 429,
        "upstream_status_code": None,
        "client_ip": request.client.host if request.client else None,
        "input_bytes": raw_input_bytes,
        "output_bytes": 0,
        "error_type": err_type,
        "error_message": message,
    }))
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    raise ApiError(429, message, err_type=env_type, code=code, headers=headers)


async def forward_chat(request: Request, auth: AuthContext) -> Response:
    app = request.app
    cfg = app.state.cfg
    db = app.state.db
    upstream = app.state.upstream
    slots = app.state.slots

    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "Invalid JSON body", code="invalid_json")
    _validate_body(body)

    stream = body.get("stream") is True
    t0 = time.monotonic()
    loop = asyncio.get_running_loop()
    raw_input_bytes = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    # ---------- Phase 11：RPM / Token 软额度（Semaphore 之前） ----------
    _enforce_limits(request, auth, body, raw_input_bytes, stream, t0)

    # ---------- Phase 8：总生命周期 deadline ----------
    deadline_loop = loop.time() + cfg.timeouts.total_request

    def remaining() -> float:
        return deadline_loop - loop.time()

    body, _injected = maybe_inject_usage(body)
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

    headers = build_upstream_headers(request.headers, upstream.api_key)
    headers["Content-Type"] = "application/json"

    record: dict = {
        "request_id": uuid.uuid4().hex,
        "user_id": auth.user_id,
        "api_key_id": auth.api_key_id,
        "backend_id": getattr(app.state, "backend_id", None),
        "model": body.get("model"),
        "endpoint": "/v1/chat/completions",
        "started_at": dao.now_ms(),
        "input_bytes": len(payload),
        "stream": int(stream),
        "client_ip": request.client.host if request.client else None,
        "queue_wait_ms": None,
    }
    rid_short = record["request_id"][:8]

    def finish(status: int, up_status: int | None, out_bytes: int,
               error_type: str | None = None, error_message: str | None = None,
               *, usage: dict | None = None, finish_reason: str | None = None,
               duration_ms: int | None = None, ttft_ms: float | None = None,
               upstream_ms: float | None = None,
               queue_wait_ms: float | None = None) -> None:
        u = usage if isinstance(usage, dict) else {}
        ptd = u.get("prompt_tokens_details")
        rec = dict(record)
        rec.update(
            finished_at=dao.now_ms(),
            duration_ms=(duration_ms if duration_ms is not None
                         else int((time.monotonic() - t0) * 1000)),
            queue_wait_ms=(int(queue_wait_ms) if queue_wait_ms is not None
                           else rec.get("queue_wait_ms")),
            upstream_duration_ms=(int(upstream_ms) if upstream_ms is not None else None),
            ttft_ms=int(ttft_ms) if ttft_ms is not None else None,
            prompt_tokens=u.get("prompt_tokens"),
            completion_tokens=u.get("completion_tokens"),
            total_tokens=u.get("total_tokens"),
            cached_tokens=(ptd or {}).get("cached_tokens") if isinstance(ptd, dict) else None,
            finish_reason=finish_reason,
            status_code=status,
            upstream_status_code=up_status,
            output_bytes=out_bytes,
            error_type=error_type,
            error_message=error_message,
        )
        # Phase 9：日志插入与 token_used 原子累加同一事务；
        # 仅当 total_tokens 可靠时累加（persist 内部判定 >0）。
        app.state.spawn(persist_request_log(
            db, rec, token_increment_for_key_id=auth.api_key_id))

    # ---------- Phase 8：Semaphore 排队（queue_timeout ≤ 总 deadline） ----------
    q_effective = min(cfg.timeouts.queue_timeout, max(remaining(), 0.0))
    try:
        logger.debug("[%s] waiting slot (timeout=%.3fs)", rid_short, q_effective)
        queue_wait_ms = await slots.acquire(timeout=q_effective)
    except SlotQueueTimeout as exc:
        logger.debug("[%s] queue timeout", rid_short)
        finish(503, None, 0, "server_busy",
               f"Upstream busy: slot queue waited {exc.waited_ms:.0f}ms",
               queue_wait_ms=exc.waited_ms)
        raise ApiError(503, "Server busy: all upstream slots are occupied",
                       err_type="api_error", code="server_busy") from None
    except asyncio.TimeoutError:
        # q_effective 受总 deadline 收敛：此处为 total_request 到期
        finish(504, None, 0, "timeout", "total request timeout while queued")
        raise ApiError(504, "Upstream request timed out",
                       err_type="api_error", code="timeout") from None

    logger.debug("[%s] slot acquired queue_wait=%.1fms", rid_short, queue_wait_ms)

    _released = {"v": False}

    def release_slot() -> None:
        """幂等释放：任何路径（含双重触发）都只允许释放一次。"""
        if _released["v"]:
            return
        _released["v"] = True
        slots.release()
        logger.debug("[%s] slot released", rid_short)

    try:
        upstream_req = upstream.client.build_request(
            "POST", "/v1/chat/completions", content=payload, headers=headers)
        try:
            t_up = time.monotonic()
            logger.debug("[%s] sending upstream stream=%s", rid_short, stream)
            if stream:
                resp = await asyncio.wait_for(
                    upstream.client.send(upstream_req, stream=True), remaining())
            else:
                resp = await asyncio.wait_for(
                    upstream.client.send(upstream_req), remaining())
            logger.debug("[%s] upstream status=%s", rid_short, resp.status_code)
        except asyncio.TimeoutError:
            finish(504, None, 0, "timeout",
                   f"total request timeout ({cfg.timeouts.total_request:.0f}s)")
            release_slot()
            raise ApiError(504, "Upstream request timed out",
                           err_type="api_error", code="timeout") from None
        except httpx.TimeoutException:
            finish(504, None, 0, "timeout", "upstream timeout")
            release_slot()
            raise ApiError(504, "Upstream request timed out",
                           err_type="api_error", code="timeout") from None
        except httpx.HTTPError:
            finish(502, None, 0, "connection_error", "cannot connect to upstream")
            release_slot()
            raise ApiError(502, "Failed to connect to upstream",
                           err_type="api_error", code="connection_error")

        content_type = resp.headers.get("content-type", "application/json")

        # ---------- 非流式路径 ----------
        if not stream:
            upstream_ms = (time.monotonic() - t_up) * 1000
            status = resp.status_code
            content: bytes = resp.content
            usage_obj: dict | None = None
            finish_reason: str | None = None
            error_type = None if 200 <= status < 400 else "upstream_error"
            if error_type is None:
                try:
                    obj = json.loads(content)
                    if isinstance(obj.get("usage"), dict):
                        usage_obj = obj["usage"]
                    choices = obj.get("choices") or [{}]
                    fr = choices[0].get("finish_reason")
                    finish_reason = fr if isinstance(fr, str) else None
                except ValueError:
                    pass
            finish(status, status, len(content), error_type,
                   None if error_type is None else f"upstream status {status}",
                   usage=usage_obj, finish_reason=finish_reason,
                   upstream_ms=upstream_ms, queue_wait_ms=queue_wait_ms)
            release_slot()
            # 规格 §40：上游错误尽量原 status + 原 body 透传
            return Response(content=content, status_code=status,
                            media_type=content_type)

        # ---------- 流式路径：上游非 200 → 读全量后透传错误 ----------
        if resp.status_code != 200:
            err_body = await resp.aread()
            await resp.aclose()
            upstream_ms = (time.monotonic() - t_up) * 1000
            finish(resp.status_code, resp.status_code, len(err_body),
                   "upstream_error", f"upstream status {resp.status_code}",
                   upstream_ms=upstream_ms, queue_wait_ms=queue_wait_ms)
            release_slot()
            return Response(content=err_body, status_code=resp.status_code,
                            media_type=content_type)

        # ---------- 流式路径：字节透传 + 扫描器旁路（ADR-0004） ----------
        # Phase 12 修复：total deadline 用 asyncio.timeout_at 包裹整个流式
        # 生命周期（墙钟生效），即使上游长时间不产任何 chunk 也会准时终止；
        # 不再依赖"下一个 chunk 到来时才发现超时"。
        async def relay_gen():
            nonlocal resp
            scanner = SseScanner()
            ttft_ms: float | None = None
            sent = 0
            error_type: str | None = None
            t_up_end: float | None = None
            logger.debug("[%s] relay start", rid_short)
            try:
                async with asyncio.timeout_at(deadline_loop):
                    async for chunk in resp.aiter_bytes():
                        scanner.feed(chunk)
                        if ttft_ms is None and scanner.data_events > 0:
                            ttft_ms = (time.monotonic() - t0) * 1000
                        sent += len(chunk)
                        yield chunk  # 原始 bytes 直接转发，禁止任何重序列化
            except TimeoutError:
                # asyncio.timeout_at 在 deadline 触发时把内部 CancelledError
                # 转换为 TimeoutError；客户端断连仍是裸 CancelledError，可区分。
                error_type = "timeout"
                logger.debug("[%s] total deadline exceeded (wall clock)", rid_short)
            except asyncio.CancelledError:
                error_type = "client_disconnected"
                logger.debug("[%s] CancelledError", rid_short)
                raise
            except GeneratorExit:
                # ASGI spec>=2.4 路径下客户端断开可能以 GeneratorExit 到达
                error_type = "client_disconnected"
                logger.debug("[%s] GeneratorExit", rid_short)
                raise
            except httpx.HTTPError as exc:
                error_type = "upstream_interrupted"
                logger.debug("[%s] HTTPError %r", rid_short, exc)
                raise
            finally:
                t_up_end = time.monotonic()
                try:
                    await resp.aclose()  # EXP-04 已验证：触发上游停止生成
                    logger.debug("[%s] upstream aclosed", rid_short)
                except Exception as exc:  # pragma: no cover
                    logger.debug("[%s] aclose failed %r", rid_short, exc)
                if error_type is None and not scanner.saw_done:
                    error_type = "upstream_interrupted"  # EOF 但无 [DONE]
                finish(resp.status_code, resp.status_code, sent, error_type, None,
                       usage=scanner.usage, finish_reason=scanner.finish_reason,
                       duration_ms=int((time.monotonic() - t0) * 1000),
                       ttft_ms=ttft_ms, upstream_ms=(
                           (t_up_end - t_up) * 1000 if t_up_end else None),
                       queue_wait_ms=queue_wait_ms)
                release_slot()
                logger.debug("[%s] finally done err=%s sent=%d", rid_short,
                             error_type, sent)

        return StreamingResponse(relay_gen(), media_type="text/event-stream",
                                 headers=STREAM_RESPONSE_HEADERS)
    except BaseException:
        # 安全网：acquire 之后、响应返回之前的任何异常路径都必须释放 slot
        release_slot()
        raise
