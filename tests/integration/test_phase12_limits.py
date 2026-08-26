"""Phase 12 验收：slots=2 / slot 计数无漂移 / RPM-Models 豁免 / 重启语义 / 配额边界。"""
from __future__ import annotations

import asyncio
import dataclasses as _dc
import httpx
import pytest
import sqlite3

from conftest import (cfg_factory, fake_llama, init_schema,  # noqa: F401
                      make_cfg, seed_key)

from easymodelgate.app import create_app

TOK = "emg_" + "Phase12xx" + "0000000000000000000000000000"


@pytest.fixture()
def asgi_app(cfg_factory, fake_llama, monkeypatch):
    """手动 lifespan 的 ASGI 应用（可访问内部状态）。"""
    monkeypatch.setenv("EMG_UPSTREAM_API_KEY", fake_llama["api_key"])

    def _make(slots=1, **timeouts):
        cfg = cfg_factory(upstream_base=fake_llama["base_url"], slots=slots)
        if timeouts:
            cfg = _dc.replace(cfg,
                              timeouts=_dc.replace(cfg.timeouts, **timeouts))
        return create_app(cfg)
    return _make


async def test_slots2_concurrent_and_no_drift(asgi_app):
    app = asgi_app(slots=2)
    async with app.router.lifespan_context(app):
        init_done = True
        seed_key(app.state.cfg.database.path, TOK)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t") as c:
            payload = {"model": "m",
                       "messages": [{"role": "u", "content": "x"}]}
            # 两并发：slots=2 下两者都不排队
            results = await asyncio.gather(*(
                c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {TOK}"},
                       json=payload) for _ in range(2)))
            assert all(r.status_code == 200 for r in results)
            assert app.state.slots.available == 2

            # 混合 30 连击（成功/上游错误交错）后计数不漂移
            for round_ in range(5):
                batch = []
                for i in range(6):
                    body = dict(payload)
                    if i % 3 == 2:
                        body["emg_case"] = "http_500"
                    batch.append(c.post("/v1/chat/completions",
                                        headers={"Authorization": f"Bearer {TOK}"},
                                        json=body))
                rs = await asyncio.gather(*batch)
                codes = [r.status_code for r in rs]
                assert all(code in (200, 500) for code in codes)
            assert app.state.slots.available == 2, "连续异常后 slot 计数不得漂移"


def test_models_exempt_from_rpm_and_quota(client):
    """明确设计：/v1/models 不计 RPM / Token Quota（已写入 README）。"""
    db = client.cfg.database.path
    kid_rpm = seed_key(db, TOK)
    con = sqlite3.connect(str(db))
    con.execute("UPDATE api_keys SET rpm_limit=1 WHERE id=?", (kid_rpm,))
    con.commit()
    con.close()
    h = {"Authorization": f"Bearer {TOK}"}
    payload = {"model": "m", "messages": [{"role": "u", "content": "x"}]}
    # RPM：第 1 次 chat 通过，第 2 次 429；models 始终放行
    assert client.post("/v1/chat/completions", headers=h, json=payload).status_code == 200
    assert client.get("/v1/models", headers=h).status_code == 200
    assert client.post("/v1/chat/completions", headers=h, json=payload).status_code == 429
    assert client.get("/v1/models", headers=h).status_code == 200

    # Quota：token_limit=0 使全部 chat 被拒，models 依然放行
    tok_q = TOK.replace("Phase12xx", "QuotaQqq")
    kid_q = seed_key(db, tok_q)
    con = sqlite3.connect(str(db))
    con.execute("UPDATE api_keys SET token_limit=0 WHERE id=?", (kid_q,))
    con.commit()
    con.close()
    hq = {"Authorization": f"Bearer {tok_q}"}
    assert client.post("/v1/chat/completions", headers=hq, json=payload).status_code == 429
    assert client.get("/v1/models", headers=hq).status_code == 200


def test_rpm_window_resets_on_process_restart(cfg_factory, fake_llama, monkeypatch):
    """RPM 计数为进程内存：重启（新 app 实例）后窗口清零——预期行为。"""
    monkeypatch.setenv("EMG_UPSTREAM_API_KEY", fake_llama["api_key"])
    cfg = cfg_factory(upstream_base=fake_llama["base_url"])
    init_schema(cfg.database.path)
    seed_key(cfg.database.path, TOK)
    import sqlite3
    con = sqlite3.connect(str(cfg.database.path))
    con.execute("UPDATE api_keys SET rpm_limit=2 WHERE key_hash=?",
                (__import__("hashlib").sha256(TOK.encode()).hexdigest(),))
    con.commit()
    con.close()

    h = {"Authorization": f"Bearer {TOK}"}
    payload = {"model": "m", "messages": [{"role": "u", "content": "x"}]}

    async def cycle(expect_third):
        app = create_app(cfg)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://t") as c:
                codes = [(await c.post("/v1/chat/completions", headers=h,
                                       json=payload)).status_code
                         for _ in range(3)]
            return codes, app

    codes1, app1 = asyncio.run(cycle(True))
    assert codes1 == [200, 200, 429]
    codes2, _ = asyncio.run(cycle(False))          # “重启”：全新 limiter
    assert codes2[0] == 200, "重启后 RPM 窗口应清零"


def test_token_used_persists_across_restart(cfg_factory, fake_llama, monkeypatch):
    monkeypatch.setenv("EMG_UPSTREAM_API_KEY", fake_llama["api_key"])
    cfg = cfg_factory(upstream_base=fake_llama["base_url"])
    init_schema(cfg.database.path)
    kid = seed_key(cfg.database.path, TOK)
    app = create_app(cfg)

    async def one_request():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://t") as c:
                r = await c.post("/v1/chat/completions",
                                 headers={"Authorization": f"Bearer {TOK}"},
                                 json={"model": "m", "messages": [
                                     {"role": "u", "content": "x"}]})
                assert r.status_code == 200

    asyncio.run(one_request())
    import time as _t
    deadline = _t.time() + 5
    used = None
    while _t.time() < deadline:
        con = sqlite3.connect(str(cfg.database.path))
        used = con.execute("SELECT token_used FROM api_keys WHERE id=?",
                           (kid,)).fetchone()[0]
        con.close()
        if used:
            break
        _t.sleep(0.05)

    # “重启”后再次读取：token_used 与 request_logs 均持久化
    app2 = create_app(cfg)

    async def verify():
        async with app2.router.lifespan_context(app2):
            pass

    asyncio.run(verify())
    con = sqlite3.connect(str(cfg.database.path))
    used2 = con.execute("SELECT token_used FROM api_keys WHERE id=?",
                        (kid,)).fetchone()[0]
    logs = con.execute("SELECT COUNT(*) FROM request_logs").fetchone()[0]
    con.close()
    assert used and used2 == used and logs >= 1


def test_quota_zero_and_over_limit(seeded):
    client, _ = seeded
    db = client.cfg.database.path

    def setq(kid, used, limit):
        con = sqlite3.connect(str(db))
        con.execute("UPDATE api_keys SET token_used=?, token_limit=? WHERE id=?",
                    (used, limit, kid))
        con.commit()
        con.close()

    k0 = seed_key(db, TOK + "0000000000000000000000zz")
    setq(k0, used=0, limit=0)
    r = client.post("/v1/chat/completions",
                    headers={"Authorization": f"Bearer {TOK + '0000000000000000000000zz'}"},
                    json={"model": "m", "messages": [{"role": "u", "content": "x"}]})
    assert r.status_code == 429                     # limit=0 → 立即拒绝
    assert r.json()["error"]["code"] == "insufficient_quota"

    k1 = seed_key(db, TOK + "0000000000000000000000yy")
    setq(k1, used=500, limit=100)                   # used > limit
    r = client.post("/v1/chat/completions",
                    headers={"Authorization": f"Bearer {TOK + '0000000000000000000000yy'}"},
                    json={"model": "m", "messages": [{"role": "u", "content": "x"}]})
    assert r.status_code == 429
