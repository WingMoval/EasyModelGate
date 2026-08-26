"""Phase 5 集成测试：流式字节透传保真、usage 注入/尊重、[DONE]、tool_calls 分片。"""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import wait_latest_log

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "fake_upstream"))
from server import (DONE_BYTES, hello_stream_chunks, multi_events_one_chunk_chunks,  # noqa: E402
                    split_event_chunks, tool_stream_chunks,
                    interrupted_no_done_chunks, get_last_request)


def _collect(seeded, **body) -> bytes:
    client, headers = seeded
    payload = {"model": "qwen3.8-local",
               "messages": [{"role": "user", "content": "hi"}], **body}
    parts: list[bytes] = []
    with client.stream("POST", "/v1/chat/completions",
                       headers=headers, json=payload) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers.get("cache-control") == "no-cache"
        assert r.headers.get("x-accel-buffering") == "no"
        for chunk in r.iter_bytes():
            parts.append(chunk)
    return b"".join(parts)


def test_stream_byte_fidelity_with_injection(seeded):
    """默认注入 include_usage=true；客户端字节 == 上游原始字节。"""
    expected = b"".join(hello_stream_chunks(include_usage=True))
    got = _collect(seeded, stream=True)
    assert got == expected, "客户端收到的 bytes 必须与 fake upstream 原始字节一致"

    client, _ = seeded
    last = get_last_request(client.fake_app)
    assert last["stream_options"] == {"include_usage": True}   # 注入生效

    row = dict(wait_latest_log(client.cfg.database.path))
    assert row["stream"] == 1
    assert row["total_tokens"] == 19 and row["cached_tokens"] == 13
    assert row["finish_reason"] == "stop"
    assert row["ttft_ms"] is not None and row["ttft_ms"] >= 0
    assert row["error_type"] is None


def test_existing_include_usage_false_respected(seeded):
    """客户端显式 false：网关不得改写；下游无 usage chunk；日志 token 为 NULL。"""
    expected = b"".join(hello_stream_chunks(include_usage=False))
    got = _collect(seeded, stream=True,
                   stream_options={"include_usage": False})
    assert got == expected
    assert b'"usage"' not in got

    client, _ = seeded
    last = get_last_request(client.fake_app)
    assert last["stream_options"] == {"include_usage": False}  # 原样保留

    row = dict(wait_latest_log(client.cfg.database.path))
    assert row["prompt_tokens"] is None and row["total_tokens"] is None
    assert row["cached_tokens"] is None


def test_existing_include_usage_true_not_touched(seeded):
    so = {"include_usage": True}
    got = _collect(seeded, stream=True, stream_options=dict(so))
    client, _ = seeded
    assert get_last_request(client.fake_app)["stream_options"] == so
    assert got == b"".join(hello_stream_chunks(include_usage=True))


def test_multi_events_in_one_chunk_passthrough(seeded):
    """一个 HTTP chunk 打包多个 SSE events：bytes 保真。"""
    expected = b"".join(multi_events_one_chunk_chunks())
    got = _collect(seeded, stream=True, emg_case="multi_in_one")
    assert got == expected
    assert got.count(b"data: ") == 5


def test_split_event_across_chunks_passthrough(seeded):
    """一个 SSE event 拆成两个 HTTP chunks：carry buffer 兜底，bytes 保真。"""
    expected = b"".join(split_event_chunks())
    got = _collect(seeded, stream=True, emg_case="split_event")
    assert got == expected


def test_done_marker_terminal(seeded):
    got = _collect(seeded, stream=True)
    assert got.endswith(DONE_BYTES)


def test_stream_tool_calls_fragmented_bytes_equal(seeded):
    """5 片 function.arguments + id/name 仅首片 + finish_reason=tool_calls；
    网关输出 bytes 与 upstream 完全一致（规格 §17 透明直通）。"""
    import json as _json
    expected = b"".join(tool_stream_chunks())
    got = _collect(seeded, stream=True, emg_case="tool_stream")
    assert got == expected
    # 结构复核：5 个分片以其 JSON 序列化形态按序出现
    pos = 0
    for frag in TOOL_ARGUMENT_FRAGMENTS_SEQ():
        needle = ('"arguments":' + _json.dumps(frag)).encode()
        idx = got.find(needle, pos)
        assert idx != -1, f"分片 {frag!r} 未在转发字节中按序出现"
        pos = idx + len(needle)
    row = dict(wait_latest_log(seeded[0].cfg.database.path))
    assert row["finish_reason"] == "tool_calls"
    assert row["total_tokens"] == 311 and row["cached_tokens"] == 281


def TOOL_ARGUMENT_FRAGMENTS_SEQ():
    from server import TOOL_ARGUMENT_FRAGMENTS
    return TOOL_ARGUMENT_FRAGMENTS


def test_stream_eof_without_done_marked_interrupted(seeded):
    """上游 EOF 但无 [DONE]：字节照常透传，日志记 upstream_interrupted。"""
    expected = b"".join(interrupted_no_done_chunks())
    got = _collect(seeded, stream=True, emg_case="no_done")
    assert got == expected
    row = dict(wait_latest_log(seeded[0].cfg.database.path))
    assert row["error_type"] == "upstream_interrupted"


def test_stream_upstream_error_status_passthrough(seeded):
    """流式请求但上游返回非 200：读全量后原样透传错误。"""
    client, headers = seeded
    payload = {"model": "m", "messages": [{"role": "user", "content": "x"}],
               "stream": True, "emg_case": "http_429"}
    r = client.post("/v1/chat/completions", headers=headers, json=payload)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limit_exceeded"
    row = dict(wait_latest_log(client.cfg.database.path))
    assert row["status_code"] == 429 and row["error_type"] == "upstream_error"
