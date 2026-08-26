"""可编程 fake llama-server（仅测试使用，非产品代码）。

v2（Phase 4-7）：
- 字节级 SSE 剧本构造器（测试用同一构造器生成期望字节，保证断言一致性）
- emg_case 分支：错误码 / 工具调用 / 分片事件 / 多事件合块 / 中途中断
- create_slow_llama_app：EXP-04 式慢速上游（断连传播验证）
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

FAKE_MODEL = "qwen3.8-local"
FAKE_USAGE = {"prompt_tokens": 17, "completion_tokens": 2, "total_tokens": 19,
              "prompt_tokens_details": {"cached_tokens": 13}}

MODELS_PAYLOAD = {
    "object": "list",
    "data": [{"id": FAKE_MODEL, "object": "model", "owned_by": "fake-llama",
              "permission": []}],
}

LAST_REQUEST_BODY: dict | None = None


def reset_last_request() -> None:
    global LAST_REQUEST_BODY
    LAST_REQUEST_BODY = None


# ---------------- 字节构造器（与 llama.cpp 线上格式一致） ----------------

def _obj_bytes(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


def _sse(obj: dict) -> bytes:
    return b"data: " + _obj_bytes(obj) + b"\n\n"


def chunk_bytes(*, delta: dict | None = None, finish: str | None = None) -> bytes:
    return _sse({
        "choices": [{"finish_reason": finish, "index": 0, "delta": delta or {}}],
        "created": 1787680000, "id": "chatcmpl-fake", "model": FAKE_MODEL,
        "system_fingerprint": "fake", "object": "chat.completion.chunk",
    })


def usage_chunk_bytes(usage: dict | None = None) -> bytes:
    return _sse({
        "choices": [], "created": 1787680000, "id": "chatcmpl-fake",
        "model": FAKE_MODEL, "system_fingerprint": "fake",
        "object": "chat.completion.chunk", "usage": usage or FAKE_USAGE,
    })


DONE_BYTES = b"data: [DONE]\n\n"


def hello_stream_chunks(*, include_usage: bool = True,
                        usage: dict | None = None) -> list[bytes]:
    """默认剧本：与 EXP-01 观测到的真实 llama.cpp 流结构一致。"""
    chunks = [
        chunk_bytes(delta={"role": "assistant", "content": None}),
        chunk_bytes(delta={"content": "hello"}),
        chunk_bytes(delta={}, finish="stop"),
    ]
    if include_usage:
        chunks.append(usage_chunk_bytes(usage))
    chunks.append(DONE_BYTES)
    return chunks


def multi_events_one_chunk_chunks() -> list[bytes]:
    """一个 HTTP chunk 内打包多个完整 SSE events。"""
    bundled = (chunk_bytes(delta={"role": "assistant", "content": None})
               + chunk_bytes(delta={"content": "hello"})
               + chunk_bytes(delta={}, finish="stop"))
    return [bundled, usage_chunk_bytes(), DONE_BYTES]


def split_event_chunks() -> list[bytes]:
    """一个 SSE event 被拆到两个 HTTP chunks（在 JSON 中部切开）。"""
    event = chunk_bytes(delta={"role": "assistant", "content": None})  # 含 \n\n
    cut = event.index(b'"delta"') + 4
    return [event[:cut], event[cut:], usage_chunk_bytes(), DONE_BYTES]


TOOL_ARGUMENT_FRAGMENTS = ["{", '"city":"', "Paris", '"', "}"]


def tool_stream_chunks() -> list[bytes]:
    """复刻 Phase 0.5 实测的 5 片 arguments 模式（EXP-03）。"""
    out: list[bytes] = []
    for i, frag in enumerate(TOOL_ARGUMENT_FRAGMENTS):
        fn: dict = {"arguments": frag}
        tc: dict = {"index": 0, "function": fn}
        if i == 0:
            tc["id"] = "call-fake-001"
            tc["type"] = "function"
            fn["name"] = "get_weather"
        out.append(chunk_bytes(delta={"tool_calls": [tc]}))
    out.append(chunk_bytes(delta={}, finish="tool_calls"))
    out.append(usage_chunk_bytes({"prompt_tokens": 285, "completion_tokens": 26,
                                  "total_tokens": 311,
                                  "prompt_tokens_details": {"cached_tokens": 281}}))
    out.append(DONE_BYTES)
    return out


def interrupted_no_done_chunks() -> list[bytes]:
    """正常发两个 chunk 后 EOF，无 [DONE] —— 网关应记 upstream_interrupted。"""
    return [chunk_bytes(delta={"role": "assistant", "content": None}),
            chunk_bytes(delta={"content": "partial"})]


NONSTREAM_PAYLOAD = {
    "id": "chatcmpl-fake", "object": "chat.completion", "created": 1787680000,
    "model": FAKE_MODEL,
    "choices": [{"index": 0,
                 "message": {"role": "assistant", "content": "hello"},
                 "finish_reason": "stop"}],
    "usage": FAKE_USAGE,
}

TOOL_NONSTREAM_PAYLOAD = {
    "id": "chatcmpl-fake", "object": "chat.completion", "created": 1787680000,
    "model": FAKE_MODEL,
    "choices": [{"index": 0,
                 "message": {
                     "role": "assistant", "content": None,
                     "tool_calls": [{"id": "call-fake-001", "type": "function",
                                     "function": {"name": "get_weather",
                                                  "arguments": '{"city":"Paris"}'}}]},
                 "finish_reason": "tool_calls"}],
    "usage": {"prompt_tokens": 285, "completion_tokens": 26, "total_tokens": 311,
              "prompt_tokens_details": {"cached_tokens": 281}},
}


_STREAM_CASES = {
    None: hello_stream_chunks,
    "plain": hello_stream_chunks,
    "multi_in_one": multi_events_one_chunk_chunks,
    "split_event": split_event_chunks,
    "tool_stream": tool_stream_chunks,
    "no_done": interrupted_no_done_chunks,
}


def create_fake_llama_app(*, require_key: str | None = "sk-test-upstream") -> FastAPI:
    app = FastAPI()
    state = {"last_request": None}

    def _auth_ok(request: Request) -> bool:
        if require_key is None:
            return True
        return request.headers.get("authorization") == f"Bearer {require_key}"

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models(request: Request):
        if not _auth_ok(request):
            return JSONResponse(status_code=401, content={
                "error": {"message": "Invalid upstream key", "type": "auth_error",
                          "param": None, "code": None}})
        return MODELS_PAYLOAD

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        if not _auth_ok(request):
            return JSONResponse(status_code=401, content={
                "error": {"message": "Invalid upstream key", "type": "auth_error",
                          "param": None, "code": None}})
        body = await request.json()
        state["last_request"] = body
        case = body.get("emg_case")

        if case in ("http_400", "http_401", "http_404", "http_429", "http_500"):
            status = int(case.split("_")[1])
            types = {400: "invalid_request_error", 401: "auth_error",
                     404: "not_found_error", 429: "rate_limit_exceeded",
                     500: "internal_error"}
            return JSONResponse(status_code=status, content={
                "error": {"message": f"fake upstream {status}",
                          "type": types[status], "param": None,
                          "code": types[status]}})
        if case == "tool_nonstream":
            return TOOL_NONSTREAM_PAYLOAD

        # 测试可注入自定义 usage（Phase 9/11 配额与累计验证）
        custom_usage = body.get("emg_usage")
        if case is None and body.get("stream") is not True:
            import copy
            payload = copy.deepcopy(NONSTREAM_PAYLOAD)
            if isinstance(custom_usage, dict):
                payload["usage"] = custom_usage
            return payload

        if body.get("stream") is True:
            if case == "interrupt":
                async def broken_gen():
                    yield hello_stream_chunks()[0]
                    await asyncio.sleep(0.02)
                    raise RuntimeError("fake upstream connection destroyed")
                return StreamingResponse(broken_gen(), media_type="text/event-stream")

            # Phase 12 静默上游：建立连接后长时间不发送任何数据
            # （验证 total_request_timeout 为墙钟 deadline）
            if body.get("emg_silent"):
                silent_for = float(body.get("emg_silent_seconds", 30))

                async def silent_gen():
                    await asyncio.sleep(silent_for)
                    yield DONE_BYTES
                return StreamingResponse(silent_gen(), media_type="text/event-stream")

            include_usage = ((body.get("stream_options") or {}).get("include_usage")
                             is True)
            if case == "plain" or case is None:
                chunks = hello_stream_chunks(include_usage=include_usage,
                                             usage=custom_usage)
            else:
                builder = _STREAM_CASES[case]
                chunks = builder()

            async def gen():
                for c in chunks:
                    yield c
                    if len(chunks) > 2:
                        await asyncio.sleep(0.01)  # 促使分帧
            return StreamingResponse(gen(), media_type="text/event-stream")

        return NONSTREAM_PAYLOAD

    app.state.fake_state = state
    return app


def get_last_request(app: FastAPI) -> dict | None:
    return app.state.fake_state["last_request"]


# ---------------- 慢速上游（断连传播验证，参照 EXP-04） ----------------

def create_slow_llama_app(log_path: str | Path, *, interval: float = 0.2,
                          duration: int = 600) -> FastAPI:
    app = FastAPI()

    def log(event: str) -> None:
        with open(log_path, "a") as f:
            f.write(json.dumps({"ts": time.time(), "event": event}) + "\n")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat(_request: Request):
        log("started")
        try:
            body = await _request.json()
        except Exception:
            body = {}
        # Phase 8 测试用：即时错误响应（不进入慢速流）
        if body.get("emg_case") == "http_500":
            return JSONResponse(status_code=500, content={
                "error": {"message": "fake slow upstream 500",
                          "type": "internal_error", "param": None,
                          "code": "internal_error"}})
        dur = int(body.get("emg_duration", duration))
        iv = float(body.get("emg_interval", interval))

        # Phase 12：静默上游（连接建立后长时间不发任何数据）
        if body.get("emg_silent"):
            silent_for = float(body.get("emg_silent_seconds", 30))

            async def silent_gen():
                log("silent_start")
                try:
                    await asyncio.sleep(silent_for)
                    yield b"data: [DONE]\n\n"
                    log("completed")
                except asyncio.CancelledError:
                    log("cancelled")
                    raise
                finally:
                    log("finally")
            return StreamingResponse(silent_gen(), media_type="text/event-stream")

        async def gen():
            try:
                for i in range(dur):
                    yield f'data: {{"t":{i}}}\n\n'.encode()
                    log(f"chunk_{i}")
                    await asyncio.sleep(iv)
                yield b"data: [DONE]\n\n"
                log("completed")
            except asyncio.CancelledError:
                log("cancelled")
                raise
            finally:
                log("finally")

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app
