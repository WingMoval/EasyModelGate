"""Phase 6 集成测试：客户端断连经真实 uvicorn 链路传播（EXP-04 模式复刻）。

链路：httpx 真实 TCP 客户端 → 网关(uvicorn 线程) → 慢速 fake 上游(uvicorn 线程)
验证：断连 → 网关取消 → upstream aclose → 上游生成器 cancelled；
      detached request log 落库 error_type=client_disconnected。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

import httpx
import pytest

from conftest import (_free_port, init_schema, make_cfg, run_server_in_thread,
                      seed_key, stop_server, VALID_TOKEN)

from server import create_slow_llama_app  # noqa: E402

from easymodelgate.app import create_app


class _Srv:
    def __init__(self, app, port):
        self.server, self.thread = run_server_in_thread(app, port)
        self.base_url = f"http://127.0.0.1:{port}"

    def stop(self):
        stop_server(self.server, self.thread)


@pytest.fixture()
def real_stack(tmp_path):
    slow_log = tmp_path / "slow.jsonl"
    slow = _Srv(create_slow_llama_app(slow_log, interval=0.1, duration=600),
                _free_port())
    cfg = make_cfg(tmp_path / "gw.db", slow.base_url)
    init_schema(cfg.database.path)
    seed_key(cfg.database.path, VALID_TOKEN)
    gw = _Srv(create_app(cfg), _free_port())
    yield {"cfg": cfg, "gw": gw, "slow": slow, "slow_log": slow_log}
    gw.stop()
    slow.stop()


def _read_log(path) -> list[dict]:
    try:
        return [json.loads(l) for l in Path(path).read_text().splitlines() if l]
    except FileNotFoundError:
        return []


async def _wait_for(predicate, timeout=6.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def test_normal_completion_real_chain(real_stack):
    """先验证同一栈上正常完成不受影响。"""
    url = real_stack["gw"].base_url + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {VALID_TOKEN}"}
    async with httpx.AsyncClient(timeout=10) as c:
        buf = b""
        async with c.stream("POST", url, headers=headers, json={
                "model": "m", "messages": [{"role":"user","content":"x"}], "emg_duration": 2,
                "emg_interval": 0.05}) as r:
            assert r.status_code == 200
            async for chunk in r.aiter_bytes():
                buf += chunk
    assert buf.endswith(b"data: [DONE]\n\n")
    db_path = real_stack["cfg"].database.path
    assert await _wait_for(lambda: _last_error_type(db_path) is None), "正常请求不应有 error_type"
    events = [e["event"] for e in _read_log(real_stack["slow_log"])]
    assert "completed" in events


async def test_client_disconnect_propagates(real_stack):
    url = real_stack["gw"].base_url + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {VALID_TOKEN}"}
    marker = time.time()

    t_disc = None
    async with httpx.AsyncClient(timeout=None) as c:
        async with c.stream("POST", url, headers=headers, json={
                "model": "m", "stream": True,
                "messages": [{"role":"user","content":"x"}]}) as r:
            assert r.status_code == 200
            start = time.monotonic()
            async for _chunk in r.aiter_bytes():
                if time.monotonic() - start >= 0.6:
                    break
            t_disc = time.time()
            await r.aclose()             # 客户端主动断开

    db_path = real_stack["cfg"].database.path
    ok = await _wait_for(lambda: _last_error_type(db_path) == "client_disconnected")
    assert ok, "detached 日志任务应在断连后落库 error_type=client_disconnected"

    row = _last_row(db_path)
    # 上游确实被取消（而非跑满 600s）
    events = [e["event"] for e in _read_log(real_stack["slow_log"])
              if e["ts"] >= marker]
    assert "cancelled" in events, f"上游应观测到 cancelled，实际：{events}"
    assert "completed" not in events
    assert row["stream"] == 1 and row["status_code"] == 200
    assert row["ttft_ms"] is not None          # 断连前已收到首个 chunk
    # 传播耗时应远小于 interval×duration；此处给宽松上限
    assert (row["finished_at"] - row["started_at"]) < 10_000
    assert t_disc is not None


def _last_row(db_path):
    import sqlite3
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        r = con.execute("SELECT * FROM request_logs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def _last_error_type(db_path):
    return _last_row(db_path).get("error_type")
