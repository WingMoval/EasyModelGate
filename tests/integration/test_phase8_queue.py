"""Phase 8 集成测试：Semaphore 排队 / queue_wait_ms / queue_timeout / total timeout。

复用真实 uvicorn 双服务器栈模式。
"""
from __future__ import annotations

import asyncio
import dataclasses as _dc
import json
import sqlite3
import time
from pathlib import Path

import httpx
import pytest

from conftest import (_free_port, init_schema, make_cfg, run_server_in_thread,
                      seed_key, stop_server, wait_latest_log, VALID_TOKEN)

from server import create_slow_llama_app  # noqa: E402

from easymodelgate.app import create_app

HDR = {"Authorization": f"Bearer {VALID_TOKEN}"}


class _Srv:
    def __init__(self, app, port):
        self.server, self.thread = run_server_in_thread(app, port)
        self.base_url = f"http://127.0.0.1:{port}"

    def stop(self):
        stop_server(self.server, self.thread)


@pytest.fixture()
def stack_factory(tmp_path):
    created = []

    def _make(**kw):
        slow_log = tmp_path / f"slow{len(created)}.jsonl"
        interval = kw.pop("slow_interval", 0.1)
        duration = kw.pop("slow_duration", 600)
        slow = _Srv(create_slow_llama_app(slow_log, interval=interval,
                                          duration=duration), _free_port())
        cfg = make_cfg(tmp_path / f"gw{len(created)}.db", slow.base_url)
        if kw:  # 定制 TimeoutsConfig 字段（frozen → replace）
            cfg = _dc.replace(cfg, timeouts=_dc.replace(cfg.timeouts, **kw))
        init_schema(cfg.database.path)
        seed_key(cfg.database.path, VALID_TOKEN)
        gw = _Srv(create_app(cfg), _free_port())
        created.append((gw, slow))
        return {"cfg": cfg, "slow": slow, "slow_log": slow_log,
                "url": gw.base_url + "/v1/chat/completions",
                "db_path": cfg.database.path}
    yield _make
    for gw, slow in created:
        gw.stop()
        slow.stop()


def _last_row(db_path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        r = con.execute("SELECT * FROM request_logs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


async def _wait_for(pred, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_second_request_queues_with_positive_queue_wait(stack_factory):
    s = stack_factory()
    async with httpx.AsyncClient(timeout=15) as c:
        first_started = asyncio.Event()

        async def hold_slot():
            async with c.stream("POST", s["url"], headers=HDR, json={
                    "model": "m", "stream": True,
                    "messages": [{"role": "user", "content": "x"}],
                    "emg_duration": 4, "emg_interval": 0.25}) as r:
                assert r.status_code == 200
                first_started.set()
                async for _ in r.aiter_bytes():
                    pass                      # 完整消费：slot 全程占用

        t_a = asyncio.create_task(hold_slot())
        await asyncio.wait_for(first_started.wait(), 5)
        await asyncio.sleep(0.3)              # 确保 A 已占 slot 并开始推理
        t_b = time.monotonic()
        r = await c.post(s["url"], headers=HDR, json={
            "model": "m", "emg_duration": 1, "emg_interval": 0.02,
            "messages": [{"role": "user", "content": "x"}]})
        waited_wall = (time.monotonic() - t_b) * 1000
        assert r.status_code == 200
        await t_a

    row = _last_row(s["db_path"])
    assert row["queue_wait_ms"] is not None and row["queue_wait_ms"] >= 50, \
        f"第二请求应观察到正排队耗时：{row['queue_wait_ms']}"
    assert row["queue_wait_ms"] <= waited_wall + 1500   # monotonic 与墙钟同量级
    assert row["upstream_duration_ms"] is not None


async def test_queue_timeout_returns_503_server_busy(stack_factory):
    s = stack_factory(queue_timeout=0.4, slow_interval=0.3)
    async with httpx.AsyncClient(timeout=15) as c:
        # 占住唯一 slot：保持 stream 上下文打开（不可对 aiter_bytes break，
        # httpx 在 break 时会自动关闭响应导致提前释放）
        hold_client = httpx.AsyncClient(timeout=None)
        ctx = hold_client.stream("POST", s["url"], headers=HDR, json={
            "model": "m", "stream": True,
            "messages": [{"role": "user", "content": "x"}],
            "emg_duration": 30})                  # 30 × 0.3s ≈ 9s 占用
        resp_a = await ctx.__aenter__()
        assert resp_a.status_code == 200
        try:
            r = await c.post(s["url"], headers=HDR, json={
                "model": "m",
                "messages": [{"role": "user", "content": "x"}]})
            assert r.status_code == 503
            assert r.json()["error"]["code"] == "server_busy"
            row = _last_row(s["db_path"])
            assert row["status_code"] == 503 and row["error_type"] == "server_busy"
            assert row["queue_wait_ms"] >= 300    # 等满 queue_timeout
            assert row["upstream_status_code"] is None   # 未触达 upstream
        finally:
            await ctx.__aexit__(None, None, None)
            await hold_client.aclose()
    # A 断开后 slot 释放，新请求可正常服务（无泄漏）
    await asyncio.sleep(0.3)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(s["url"], headers=HDR, json={
            "model": "m", "emg_duration": 1, "emg_interval": 0.01,
            "messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 200


async def test_upstream_error_releases_slot(stack_factory):
    s = stack_factory()
    url = s["url"]
    async with httpx.AsyncClient(timeout=10) as c:
        r1 = await c.post(url, headers=HDR, json={
            "model": "m", "emg_case": "http_500",
            "messages": [{"role": "user", "content": "x"}]})
        assert r1.status_code == 500
        t0 = time.monotonic()
        r2 = await c.post(url, headers=HDR, json={
            "model": "m", "emg_duration": 1, "emg_interval": 0.01,
            "messages": [{"role": "user", "content": "x"}]})
        elapsed = time.monotonic() - t0
        assert r2.status_code == 200
        assert elapsed < 5, "slot 应已释放（无排队阻塞）"
    row = _last_row(s["db_path"])
    assert row["error_type"] is None


async def test_total_timeout_non_stream_closes_upstream(stack_factory):
    s = stack_factory(total_request=0.6, slow_interval=0.05)
    async with httpx.AsyncClient(timeout=15) as c:
        t0 = time.monotonic()
        r = await c.post(s["url"], headers=HDR, json={
            "model": "m",
            "messages": [{"role": "user", "content": "x"}],
            "emg_duration": 30})   # 上游迟迟不返回完整 JSON
        wall = (time.monotonic() - t0) * 1000
        assert r.status_code == 504
        assert r.json()["error"]["code"] == "timeout"
        assert 500 <= wall <= 4000
    row = _last_row(s["db_path"])
    assert row["status_code"] == 504 and row["error_type"] == "timeout"
    events = [json.loads(l)["event"]
              for l in Path(s["slow_log"]).read_text().splitlines()]
    assert "cancelled" in events or "finally" in events, "上游应被关闭"


async def test_total_timeout_streaming_aborts_and_logs(stack_factory):
    s = stack_factory(total_request=0.8, slow_interval=0.1)
    async with httpx.AsyncClient(timeout=15) as c:
        buf = b""
        async with c.stream("POST", s["url"], headers=HDR, json={
                "model": "m", "stream": True,
                "messages": [{"role": "user", "content": "x"}],
                "emg_duration": 60}) as r:
            assert r.status_code == 200
            async for chunk in r.aiter_bytes():
                buf += chunk
        assert len(buf) > 0                       # 已收到部分数据后被切断
    # 独立 stack 库仅一个请求：轮询等待 detached 日志任务落库
    # （单次原子 INSERT，row 出现即终态），消除 _last_row 零等待 race
    row = wait_latest_log(s["db_path"])
    assert row["error_type"] == "timeout"
    assert row["ttft_ms"] is not None
