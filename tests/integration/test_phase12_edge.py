"""Phase 12 验收：total_request_timeout 墙钟语义 / Auth 边界 / Validation 边界。

重点回归（任务书 §九/§二十五.1）：
上游建立连接后长时间不发送任何数据时，total deadline 必须准时终止，
不能依赖"下一个 chunk 到达"。
"""
from __future__ import annotations

import asyncio
import dataclasses as _dc
import time

import httpx
import pytest

from conftest import (_free_port, init_schema, make_cfg, run_server_in_thread,
                      seed_key, stop_server, VALID_TOKEN, auth_header)

from server import create_slow_llama_app  # noqa: E402

from easymodelgate.app import create_app


class _Srv:
    def __init__(self, app, port):
        self.server, self.thread = run_server_in_thread(app, port)
        self.base_url = f"http://127.0.0.1:{port}"

    def stop(self):
        stop_server(self.server, self.thread)


async def test_total_timeout_is_wall_clock_on_silent_upstream(tmp_path):
    """上游 30s 静默：deadline=0.6s 必须在 ~0.6s 终止（墙钟），而非等 chunk。"""
    slow_log = tmp_path / "slow.jsonl"
    slow = _Srv(create_slow_llama_app(slow_log, interval=0.05, duration=600),
                _free_port())
    cfg = make_cfg(tmp_path / "gw.db", slow.base_url)
    cfg = _dc.replace(cfg,
                      timeouts=_dc.replace(cfg.timeouts,
                                           total_request=0.6, read=None))
    init_schema(cfg.database.path)
    seed_key(cfg.database.path, VALID_TOKEN)
    gw = _Srv(create_app(cfg), _free_port())
    try:
        url = gw.base_url + "/v1/chat/completions"
        async with httpx.AsyncClient(timeout=None) as c:
            t0 = time.monotonic()
            buf = b""
            async with c.stream("POST", url, headers=auth_header(VALID_TOKEN),
                                json={"model": "m", "stream": True,
                                      "messages": [{"role": "user", "content": "x"}],
                                      "emg_silent": True,
                                      "emg_silent_seconds": 30}) as r:
                assert r.status_code == 200          # 头已发出，之后被切断
                async for chunk in r.aiter_bytes():
                    buf += chunk
            wall = time.monotonic() - t0
        assert len(buf) == 0                          # 静默期无任何数据
        assert wall < 2.5, f"deadline 未按墙钟生效，耗时 {wall:.2f}s"

        deadline_ms = (time.monotonic() - t0) * 0  # placeholder避免未用告警

        # 落库断言
        con_path = str(cfg.database.path)
        for _ in range(60):
            import sqlite3
            con = sqlite3.connect(con_path)
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT error_type FROM request_logs "
                              "ORDER BY id DESC LIMIT 1").fetchone()
            con.close()
            if row and row["error_type"] == "timeout":
                break
            await asyncio.sleep(0.05)
        assert row is not None and row["error_type"] == "timeout"
    finally:
        gw.stop()
        slow.stop()


# ---------------- Auth 边界（不允许 500） ----------------

@pytest.fixture()
def authed_client(client):
    seed_key(client.cfg.database.path, VALID_TOKEN)
    return client


@pytest.mark.parametrize("headers,label", [
    ({}, "no-auth"),
    ({"Authorization": ""}, "empty"),
    ({"Authorization": "Bearer"}, "bare-bearer"),
    ({"Authorization": "Bearer "}, "bearer-space"),
    ({"Authorization": "Bearer    "}, "bearer-spaces"),
    ({"Authorization": "Token abc"}, "wrong-scheme"),
    ({"Authorization": "Bearer sk-not-emg-key"}, "wrong-prefix"),
    ({"Authorization": "Bearer emg_notexistkey000000000000notexist"},
     "nonexistent"),
    ({"Authorization": "Bearer emg_" + "x" * 8000}, "oversized"),
])
def test_auth_edges_never_500(authed_client, headers, label):
    r = authed_client.get("/v1/models", headers=headers)
    assert r.status_code in (401, 403), f"{label} → {r.status_code}"
    assert r.status_code != 500
    err = r.json()["error"]
    assert set(err) >= {"message", "type", "param", "code"}


def test_double_space_with_valid_key_is_lenient(authed_client):
    """多余空白 + 有效 Key：宽容接受（与 OpenAI SDK 行为一致，非安全问题）。"""
    r = authed_client.get("/v1/models",
                          headers={"Authorization": f"Bearer  {VALID_TOKEN}"})
    assert r.status_code == 200


def test_bearer_case_insensitive_scheme(authed_client):
    r = authed_client.get("/v1/models",
                          headers={"Authorization": f"bearer {VALID_TOKEN}"})
    assert r.status_code == 200


# ---------------- Request validation 边界 ----------------

def _post_raw(client, headers, raw: bytes):
    h = dict(headers)
    h["Content-Type"] = "application/json"
    return client.request("POST", "/v1/chat/completions", headers=h, content=raw)


def test_validation_body_not_json(seeded):
    _, headers = seeded
    r = _post_raw(seeded[0], headers, b"{not json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_json"


def test_validation_body_array(seeded):
    _, headers = seeded
    r = seeded[0].request("POST", "/v1/chat/completions", headers=headers,
                          content=b"[1,2,3]",
                          )
    r.headers.update({"Content-Type": "application/json"})
    r2 = _post_raw(seeded[0], headers, b"[1,2,3]")
    assert r2.status_code == 400 and r2.json()["error"]["code"] == "invalid_request_body"


def test_validation_body_null(seeded):
    _, headers = seeded
    r = _post_raw(seeded[0], headers, b"null")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request_body"


def test_validation_messages_missing_empty_wrong_type(seeded):
    _, headers = seeded
    for payload, code in [
        ({"model": "m"}, "invalid_messages"),
        ({"model": "m", "messages": []}, "invalid_messages"),
        ({"model": "m", "messages": "abc"}, "invalid_messages"),
        ({"model": "m", "messages": [1, 2]}, "invalid_messages"),
    ]:
        r = seeded[0].post("/v1/chat/completions", headers=headers, json=payload)
        assert r.status_code == 400, payload
        assert r.json()["error"]["code"] == code, payload


def test_validation_model_non_string(seeded):
    _, headers = seeded
    r = seeded[0].post("/v1/chat/completions", headers=headers, json={
        "model": 42, "messages": [{"role": "u", "content": "x"}]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_model"


def test_validation_stream_non_bool_forwarded_transparently(seeded):
    """stream='yes' 字符串：网关不报错、不改写、按非流式路由并透传。"""
    from server import get_last_request
    client, headers = seeded
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "m", "stream": "yes",
        "messages": [{"role": "u", "content": "x"}]})
    assert r.status_code == 200                      # 宽松路由，透传给上游
    assert get_last_request(client.fake_app)["stream"] == "yes"


def test_large_but_reasonable_json(seeded):
    client, headers = seeded
    big = "x" * 500_000
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "m", "messages": [{"role": "u", "content": big}]})
    assert r.status_code == 200
    row = wait_latest_log(client.cfg.database.path)
    assert row["input_bytes"] > 500_000              # 大 body 正常计数


from conftest import wait_latest_log  # noqa: E402
