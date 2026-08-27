"""Phase 11 集成测试：RPM 固定窗口与 Token 软额度。"""
from __future__ import annotations

import sqlite3

from conftest import init_schema, seed_key, wait_latest_log

from easymodelgate.app import create_app  # noqa: E402

TOKEN_A = "emg_" + "Rpm11Aaa" + "0000000000000000000000000000"
TOKEN_B = "emg_" + "Rpm22Bbb" + "1111111111111111111111111111"


def _token_used(db_path, key_id):
    con = sqlite3.connect(str(db_path))
    try:
        return con.execute("SELECT token_used FROM api_keys WHERE id=?",
                           (key_id,)).fetchone()[0]
    finally:
        con.close()


def _set_limits(db_path, key_id, *, used=None, limit=None, rpm=None):
    con = sqlite3.connect(str(db_path))
    try:
        if used is not None:
            con.execute("UPDATE api_keys SET token_used=? WHERE id=?", (used, key_id))
        if limit is not None or rpm is not None:
            con.execute("UPDATE api_keys SET token_limit=?, rpm_limit=? WHERE id=?",
                        (limit, rpm, key_id))
        con.commit()
    finally:
        con.close()


def test_rpm_null_unlimited(seeded):
    client, headers = seeded
    seed_key(client.cfg.database.path, TOKEN_A)          # rpm_limit NULL
    for _ in range(12):
        r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {TOKEN_A}"},
                        json={"model": "m", "messages": [{"role": "u", "content": "x"}]})
        assert r.status_code == 200


def test_rpm_limit_blocks_and_logs(seeded):
    """前 N 次通过；第 N+1 次 429+Retry-After；拒绝不触达 upstream 且落库。"""
    client, _ = seeded
    db = client.cfg.database.path
    kid = seed_key(db, TOKEN_B)
    _set_limits(db, kid, rpm=2)

    h = {"Authorization": f"Bearer {TOKEN_B}"}
    ok_codes = [client.post("/v1/chat/completions", headers=h,
                            json={"model": "m",
                                  "messages": [{"role": "u", "content": "x"}]}).status_code
                for _ in range(2)]
    assert ok_codes == [200, 200]

    from server import get_last_request
    before = get_last_request(client.fake_app)

    r = client.post("/v1/chat/completions", headers=h,
                    json={"model": "m", "messages": [{"role": "u", "content": "x"}]})
    assert r.status_code == 429
    body = r.json()["error"]
    assert body["code"] == "rate_limit_exceeded"
    assert body["type"] == "rate_limit_error"
    retry_after = r.headers.get("retry-after")
    assert retry_after is not None and int(retry_after) >= 1

    row = dict(wait_latest_log(db))
    assert row["status_code"] == 429 and row["error_type"] == "rate_limited"
    assert row["queue_wait_ms"] == 0
    assert row["upstream_status_code"] is None
    assert get_last_request(client.fake_app) == before   # 未触达 upstream


def test_rpm_isolated_between_keys(seeded):
    client, _ = seeded
    db = client.cfg.database.path
    ka = seed_key(db, TOKEN_A)
    kb = seed_key(db, TOKEN_B)
    _set_limits(db, ka, rpm=1)
    ha = {"Authorization": f"Bearer {TOKEN_A}"}
    hb = {"Authorization": f"Bearer {TOKEN_B}"}
    payload = {"model": "m", "messages": [{"role": "u", "content": "x"}]}
    assert client.post("/v1/chat/completions", headers=ha, json=payload).status_code == 200
    assert client.post("/v1/chat/completions", headers=ha, json=payload).status_code == 429
    assert client.post("/v1/chat/completions", headers=hb, json=payload).status_code == 200
    assert kb > 0 and ka > 0


def test_quota_soft_overrun_and_reject(seeded):
    """used=90 < limit=100：允许完成（usage 20 → used=110）；下一请求拒绝。"""
    client, _ = seeded
    db = client.cfg.database.path
    kid = seed_key(db, TOKEN_A)
    _set_limits(db, kid, used=90, limit=100)

    h = {"Authorization": f"Bearer {TOKEN_A}"}
    usage20 = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20,
               "prompt_tokens_details": {"cached_tokens": 0}}
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "m", "messages": [{"role": "u", "content": "x"}],
        "emg_usage": usage20})
    assert r.status_code == 200                            # soft overrun 允许本次

    deadline_dependent_row = dict(wait_latest_log(db))
    assert deadline_dependent_row["total_tokens"] == 20
    first_row_id = deadline_dependent_row["id"]        # 第一请求日志的稳定标识

    used_after = None
    import time as _t
    for _ in range(50):
        used_after = _token_used(db, kid)
        if used_after >= 110:
            break
        _t.sleep(0.05)
    assert used_after == 110, f"token_used 应原子累加到 110，实际 {used_after}"

    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "m", "messages": [{"role": "u", "content": "x"}]})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "insufficient_quota"
    # 等待"新 row"（id > 第一请求日志 id），避免 detached 落库未 commit 时
    # 误读第一请求的旧 row（单次原子 INSERT：row 出现即终态）
    row = dict(wait_latest_log(db, after_id=first_row_id))
    assert row["error_type"] == "quota_exceeded" and row["queue_wait_ms"] == 0


def test_quota_unlimited_and_below_limit(seeded):
    client, _ = seeded
    db = client.cfg.database.path
    kid = seed_key(db, TOKEN_B)                            # token_limit NULL
    _set_limits(db, kid, used=999999)
    h = {"Authorization": f"Bearer {TOKEN_B}"}
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "m", "messages": [{"role": "u", "content": "x"}]})
    assert r.status_code == 200                            # unlimited 不受 used 影响

    kid2 = seed_key(db, TOKEN_A)
    _set_limits(db, kid2, used=5, limit=100)
    h2 = {"Authorization": f"Bearer {TOKEN_A}"}
    r = client.post("/v1/chat/completions", headers=h2, json={
        "model": "m", "messages": [{"role": "u", "content": "x"}],
        "emg_usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2,
                      "prompt_tokens_details": {"cached_tokens": 0}}})
    assert r.status_code == 200
    import time as _t
    deadline = _t.time() + 5
    while _t.time() < deadline and _token_used(db, kid2) < 7:
        _t.sleep(0.05)
    assert _token_used(db, kid2) == 7


def test_no_usage_no_increment(seeded):
    """usage 缺失（include_usage=false）→ 不估算、不累加。"""
    client, _ = seeded
    db = client.cfg.database.path
    kid = seed_key(db, TOKEN_A)
    _set_limits(db, kid, used=10)
    h = {"Authorization": f"Bearer {TOKEN_A}"}
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "m", "stream": True, "stream_options": {"include_usage": False},
        "messages": [{"role": "u", "content": "x"}]})
    assert r.status_code == 200
    import time as _t
    deadline = _t.time() + 3
    while _token_used(db, kid) != 10 and _t.time() < deadline:
        _t.sleep(0.05)
    assert _token_used(db, kid) == 10                      # 未增加


def test_concurrent_token_used_atomic(cfg_factory, fake_llama, monkeypatch):
    """8 个并发请求各产生 5 tokens：累计必须精确 +40（无 lost update）。"""
    import asyncio
    import httpx

    monkeypatch.setenv("EMG_UPSTREAM_API_KEY", fake_llama["api_key"])
    cfg = cfg_factory(upstream_base=fake_llama["base_url"])
    init_schema(cfg.database.path)
    kid = seed_key(cfg.database.path, TOKEN_A)
    _set_limits(cfg.database.path, kid, used=0)
    app = create_app(cfg)

    async def run():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://testserver") as ac:
                async def one():
                    r = await ac.post("/v1/chat/completions", headers={
                        "Authorization": f"Bearer {TOKEN_A}"}, json={
                        "model": "m", "messages": [{"role": "u", "content": "x"}],
                        "emg_usage": {"prompt_tokens": 2, "completion_tokens": 3,
                                      "total_tokens": 5,
                                      "prompt_tokens_details": {"cached_tokens": 1}}})
                    assert r.status_code == 200
                await asyncio.gather(*(one() for _ in range(8)))

    asyncio.run(run())

    import time as _t
    deadline = _t.time() + 5
    while _t.time() < deadline:
        if _token_used(cfg.database.path, kid) >= 40:
            break
        _t.sleep(0.05)
    assert _token_used(cfg.database.path, kid) == 40, "并发累加必须无 lost update"
