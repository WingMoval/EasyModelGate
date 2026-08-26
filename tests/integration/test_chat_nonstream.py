"""Phase 4 集成测试：non-stream 透传、usage 落库、上游错误透传、连接失败/超时。"""
from __future__ import annotations

import sqlite3

import pytest

from conftest import seed_key, wait_latest_log, VALID_TOKEN, auth_header

from easymodelgate.app import create_app
from easymodelgate.config import AppConfig
from fastapi.testclient import TestClient


def _post(seeded, **body):
    client, headers = seeded
    payload = {"model": "qwen3.8-local",
               "messages": [{"role": "user", "content": "hi"}], **body}
    return client.post("/v1/chat/completions", headers=headers, json=payload)


def test_nonstream_passthrough_and_usage_logged(seeded):
    client, headers = seeded
    r = _post(seeded)
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hello"

    row = wait_latest_log(client.cfg.database.path)
    assert row is not None
    d = dict(row)
    assert d["stream"] == 0
    assert d["status_code"] == 200 and d["upstream_status_code"] == 200
    assert d["prompt_tokens"] == 17 and d["completion_tokens"] == 2
    assert d["total_tokens"] == 19 and d["cached_tokens"] == 13
    assert d["finish_reason"] == "stop"
    assert d["error_type"] is None
    assert d["input_bytes"] > 0 and d["output_bytes"] > 0
    assert d["endpoint"] == "/v1/chat/completions"
    assert d["model"] == "qwen3.8-local"
    assert d["request_id"] and len(d["request_id"]) == 32
    # 隐私原则：日志表不含任何内容列（schema 层面即无）
    import sqlite3
    con = sqlite3.connect(str(client.cfg.database.path))
    cols = {r[1] for r in con.execute("PRAGMA table_info(request_logs)")}
    con.close()
    assert not cols & {"messages", "prompt", "response", "reasoning_content"}


def test_nonstream_tool_calls_logged(seeded):
    client, headers = seeded
    r = _post(seeded, emg_case="tool_nonstream")
    assert r.status_code == 200
    body = r.json()
    tc = body["choices"][0]["message"]["tool_calls"][0]
    assert tc["function"]["name"] == "get_weather"
    assert tc["function"]["arguments"] == '{"city":"Paris"}'
    assert body["choices"][0]["finish_reason"] == "tool_calls"

    row = dict(wait_latest_log(client.cfg.database.path))
    assert row["finish_reason"] == "tool_calls"
    assert row["total_tokens"] == 311 and row["cached_tokens"] == 281


@pytest.mark.parametrize("case,status", [("http_400", 400), ("http_429", 429),
                                         ("http_500", 500)])
def test_upstream_error_passthrough(seeded, case, status):
    """规格 §40：原 status + 原 body 透传给客户端。"""
    client, headers = seeded
    r = _post(seeded, emg_case=case)
    assert r.status_code == status
    err = r.json()["error"]
    assert err["message"] == f"fake upstream {status}"

    row = dict(wait_latest_log(client.cfg.database.path))
    assert row["status_code"] == status
    assert row["upstream_status_code"] == status
    assert row["error_type"] == "upstream_error"
    # 上游错误也必须有 usage 为 NULL 的容忍（fake 错误响应无 usage）
    assert row["total_tokens"] is None


def test_connect_failure_maps_502(cfg_factory):
    cfg = cfg_factory(upstream_base="http://127.0.0.1:1")  # 关闭端口 → 拒连
    import os
    os.environ["EMG_UPSTREAM_API_KEY"] = ""
    try:
        with TestClient(create_app(cfg)) as client:
            seed_key(cfg.database.path, VALID_TOKEN)
            r = client.post("/v1/chat/completions", headers=auth_header(VALID_TOKEN),
                            json={"model": "m", "messages": [{"role": "user", "content": "x"}]})
            assert r.status_code == 502
            assert r.json()["error"]["code"] == "connection_error"
            row = dict(wait_latest_log(cfg.database.path))
            assert row["status_code"] == 502
            assert row["upstream_status_code"] is None
            assert row["error_type"] == "connection_error"
    finally:
        os.environ.pop("EMG_UPSTREAM_API_KEY", None)


def test_connect_timeout_maps_504(tmp_path):
    """read=None 冻结下，超时路径由 connect 超时覆盖（不可路由地址）。"""
    cfg = AppConfig(
        database=__import__("easymodelgate.config", fromlist=["DatabaseConfig"]).DatabaseConfig(
            path=str(tmp_path / "t.db")),
        upstream=__import__("easymodelgate.config", fromlist=["UpstreamConfig"]).UpstreamConfig(
            base_url="http://192.0.2.1:81"),
        timeouts=__import__("easymodelgate.config", fromlist=["TimeoutsConfig"]).TimeoutsConfig(
            connect=0.5),
    )
    with TestClient(create_app(cfg)) as client:
        seed_key(cfg.database.path, VALID_TOKEN)
        r = client.post("/v1/chat/completions", headers=auth_header(VALID_TOKEN),
                        json={"model": "m", "messages": [{"role": "user", "content": "x"}]},
                        )
        assert r.status_code == 504, r.text
        assert r.json()["error"]["code"] == "timeout"
        row = dict(wait_latest_log(cfg.database.path))
        assert row["error_type"] == "timeout"


def test_invalid_body_rejected_without_upstream_call(seeded):
    client, headers = seeded
    r = client.request("POST", "/v1/chat/completions", headers=headers,
                       content=b"{not json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_json"

    r = client.post("/v1/chat/completions", headers=headers,
                    json=[1, 2, 3])
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request_body"

    r = client.post("/v1/chat/completions", headers=headers,
                    json={"messages": []})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_messages"

    r = client.post("/v1/chat/completions", headers=headers,
                    json={"messages": [{"role": "u"}], "model": 123})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_model"


def test_unknown_fields_forwarded_verbatim(seeded):
    """规格 §11：未知字段不得被静默丢弃——fake 会记录收到的 body。"""
    from server import get_last_request
    client, headers = seeded
    future_field = {"web_search_options": {"search_context_size": "high"},
                    "reasoning_effort": "high", "some_future_knob": {"a": [1, 2]}}
    r = _post(seeded, **future_field)
    assert r.status_code == 200
    last = get_last_request(client.fake_app)
    for k, v in future_field.items():
        assert last.get(k) == v, f"字段 {k} 未被透明转发"
