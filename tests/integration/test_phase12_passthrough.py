"""Phase 12 验收：Tool Calling / 未知字段透传补充 + 上游错误矩阵扩展。"""
from __future__ import annotations

import pytest

from server import get_last_request


def test_tool_request_fields_forwarded_verbatim(seeded):
    """parallel_tool_calls / response_format / reasoning_effort 等字段必须原样转发。"""
    client, headers = seeded
    fields = {
        "parallel_tool_calls": False,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "x", "schema": {"type": "object"}}},
        "reasoning_effort": "high",
        "reasoning_content": {"hint": "keep"},
        "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
    }
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "m",
        "messages": [{"role": "user", "content": "weather?"}],
        "tools": [{"type": "function", "function": {
            "name": "get_weather", "parameters": {"type": "object"}}}],
        **fields})
    assert r.status_code == 200
    last = get_last_request(client.fake_app)
    for k, v in fields.items():
        assert last.get(k) == v, f"{k} 未被透明转发"


def test_tool_nonstream_response_semantics_untouched(seeded):
    """响应语义一致：tool_calls 结构、arguments、finish_reason 均为上游原样。"""
    client, headers = seeded
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "m", "messages": [{"role": "u", "content": "w"}],
        "emg_case": "tool_nonstream"})
    body = r.json()
    msg = body["choices"][0]["message"]
    assert msg["tool_calls"][0]["function"]["arguments"] == '{"city":"Paris"}'
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    # 网关不得添加无关顶层字段
    assert set(body.keys()) == {"id", "object", "created", "model",
                                "choices", "usage"}


@pytest.mark.parametrize("case,status", [("http_400", 400), ("http_401", 401),
                                         ("http_404", 404), ("http_429", 429),
                                         ("http_500", 500)])
def test_upstream_error_matrix_full(seeded, case, status):
    """§40 全矩阵：原 status + 原 body 透传，且落库 upstream_status_code。"""
    client, headers = seeded
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "m", "messages": [{"role": "u", "content": "x"}],
        "emg_case": case})
    assert r.status_code == status
    assert r.json()["error"]["message"] == f"fake upstream {status}"
    from conftest import wait_latest_log
    row = dict(wait_latest_log(client.cfg.database.path))
    assert row["upstream_status_code"] == status
    assert row["error_type"] == "upstream_error"
