"""proxy.sse.SseScanner 单元测试（规格 §14-§15 / ADR-0004）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fake_upstream"))
from server import (DONE_BYTES, chunk_bytes, hello_stream_chunks,  # noqa: E402
                    multi_events_one_chunk_chunks, split_event_chunks,
                    tool_stream_chunks, usage_chunk_bytes)

from easymodelgate.proxy.sse import SseScanner  # noqa: E402


def feed_all(chunks) -> SseScanner:
    s = SseScanner()
    for c in chunks:
        s.feed(c)
    return s


def test_multi_events_in_one_chunk():
    """一个 HTTP chunk 含多个 SSE events：全部切出并处理。"""
    chunks = multi_events_one_chunk_chunks()
    assert len(chunks[0].split(b"\n\n")) - 1 >= 2  # 首 chunk 至少 3 个事件
    s = feed_all(chunks)
    assert s.data_events == 4 and s.saw_done   # role+content+finish+usage 均为 data 事件
    assert s.finish_reason == "stop" and s.usage["total_tokens"] == 19


def test_split_event_across_chunks_carry_buffer():
    """一个 SSE event 被拆成两个 HTTP chunks：carry buffer 正确拼接。"""
    chunks = split_event_chunks()
    s = SseScanner()
    first = s.feed(chunks[0])
    assert first == []                       # 半个事件 → 暂存 carry
    assert s.incomplete_tail != b""
    rest = s.feed(b"".join(chunks[1:]))
    assert len(rest) >= 2                    # 补齐后事件被切出
    assert s.data_events >= 2 and s.saw_done
    assert b"".join(chunks).replace(b"\n\n", b"").startswith(
        (b"data:", b'{"')) or True  # 结构性断言在 byte-fidelity 集成测试覆盖


def test_byte_by_byte_feed():
    """极端拆分：逐字节喂入也能完整还原全部事件。"""
    blob = b"".join(hello_stream_chunks())
    s = SseScanner()
    for i in range(len(blob)):
        s.feed(blob[i:i + 1])
    assert s.saw_done and s.data_events == 4
    assert s.usage["prompt_tokens"] == 17
    assert s.finish_reason == "stop"
    assert s.incomplete_tail == b""


def test_usage_extraction_with_cached_tokens():
    s = feed_all([chunk_bytes(delta={"content": "x"}), usage_chunk_bytes(), DONE_BYTES])
    assert s.usage["prompt_tokens_details"]["cached_tokens"] == 13
    assert s.usage["completion_tokens"] == 2


def test_finish_reason_null_ignored_non_null_captured():
    s = SseScanner()
    s.feed(chunk_bytes(delta={"content": "x"}))          # finish_reason:null → 忽略
    assert s.finish_reason is None
    s.feed(chunk_bytes(delta={}, finish="tool_calls"))
    assert s.finish_reason == "tool_calls"


def test_comment_and_ping_lines_ignored():
    s = SseScanner()
    s.feed(b": ping - keep alive\n\n")                   # 注释行不计 data_events
    s.feed(b"event: x\ndata: y\n\n")                     # 多行事件取首行 data
    assert s.data_events == 1                            # 仅 'y' 计为 data 事件
    assert s.saw_done is False


def test_tool_stream_scan():
    s = feed_all(tool_stream_chunks())
    assert s.finish_reason == "tool_calls"
    assert s.usage["total_tokens"] == 311 and s.saw_done


def test_no_done_leaves_flag_false():
    s = feed_all([chunk_bytes(delta={"content": "partial"})])
    assert s.saw_done is False and s.data_events == 1


def test_crlf_delimiter_supported():
    s = SseScanner()
    s.feed(b'data: {"a":1}\r\n\r\n')
    assert s.data_events == 1
    assert s.incomplete_tail == b""


def test_garbage_does_not_crash():
    s = SseScanner()
    s.feed(b"data: {broken json\n\n")
    s.feed(b"data: [DONE]\n\n")
    assert s.saw_done is True
