"""Phase 12 验收：轻量并发压测（fake 上游）+ 后台任务清理检查。"""
from __future__ import annotations

import asyncio
import sqlite3
import time

import httpx
import pytest

from conftest import cfg_factory, fake_llama, init_schema, seed_key  # noqa: F401

from easymodelgate.app import create_app

TOK = "emg_" + "Load12xx" + "0000000000000000000000000000"


async def _load(cfg_factory, fake_llama, monkeypatch, slots: int,
                total: int, concurrency: int):
    monkeypatch.setenv("EMG_UPSTREAM_API_KEY", fake_llama["api_key"])
    cfg = cfg_factory(upstream_base=fake_llama["base_url"], slots=slots)
    init_schema(cfg.database.path)
    seed_key(cfg.database.path, TOK)
    app = create_app(cfg)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t", timeout=30) as c:
            sem = asyncio.Semaphore(concurrency)
            t0 = time.monotonic()

            async def one(i: int):
                async with sem:
                    body = {"model": "m",
                            "messages": [{"role": "u", "content": f"n{i}"}],
                            "emg_usage": {"prompt_tokens": 2,
                                          "completion_tokens": 3,
                                          "total_tokens": 5,
                                          "prompt_tokens_details":
                                              {"cached_tokens": 1}}}
                    if i % 10 == 7:
                        body["emg_case"] = "http_500"
                    r = await c.post("/v1/chat/completions",
                                     headers={"Authorization": f"Bearer {TOK}"},
                                     json=body)
                    return r.status_code

            codes = await asyncio.gather(*(one(i) for i in range(total)))
            wall = time.monotonic() - t0
            db_path = str(cfg.database.path)

    # lifespan 已退出：后台任务应全部清空（无 task 泄漏）
    assert len(app.state.background_tasks) == 0, \
        f"shutdown 后 background_tasks 未清空"
    # slot 计数回到满值（无泄漏）
    assert app.state.slots.available == slots
    return codes, wall, db_path


def _stats(codes):
    ok = sum(1 for c in codes if c == 200)
    up_err = sum(1 for c in codes if c == 500)
    unexpected = sorted({c for c in codes if c not in (200, 500)})
    return ok, up_err, unexpected


def test_load_slots_1(cfg_factory, fake_llama, monkeypatch):
    codes, wall, _ = asyncio.run(_load(cfg_factory, fake_llama, monkeypatch,
                                       slots=1, total=50, concurrency=10))
    ok, up_err, unexpected = _stats(codes)
    print(f"\n[slots=1] total={len(codes)} ok={ok} upstream_500={up_err} "
          f"unexpected={unexpected} wall={wall:.2f}s")
    assert not unexpected and not up_err > 50 // 10 + 2


def test_load_slots_2(cfg_factory, fake_llama, monkeypatch):
    codes, wall, db_path = asyncio.run(_load(
        cfg_factory, fake_llama, monkeypatch, slots=2, total=60, concurrency=12))
    ok, up_err, unexpected = _stats(codes)
    print(f"\n[slots=2] total={len(codes)} ok={ok} upstream_500={up_err} "
          f"unexpected={unexpected} wall={wall:.2f}s")
    assert not unexpected

    # token_used 精确等于 5 × 成功请求数（并发一致性）
    deadline = time.time() + 5
    used = None
    while time.time() < deadline:
        con = sqlite3.connect(db_path)
        used = con.execute("SELECT token_used FROM api_keys WHERE key_prefix=?",
                           (TOK[:12],)).fetchone()[0]
        con.close()
        if used >= 5 * (ok - 1):      # 允许最后一次 flush 延迟，随后精确断言
            break
        time.sleep(0.05)
    assert used == 5 * ok, f"token_used={used} 应为 5×{ok}"
