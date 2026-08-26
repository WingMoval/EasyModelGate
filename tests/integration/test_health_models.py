"""集成冒烟：/health、/v1/models 鉴权矩阵、上游透传与头处理（Phase 3）。"""
from __future__ import annotations

import time

from server import MODELS_PAYLOAD

from conftest import auth_header, seed_key

VALID_TOKEN = "emg_" + "A1b2C3d4" + "IntegrationTestToken000000000"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"


def test_models_requires_auth(client, cfg_factory):
    db_path = client.cfg.database.path
    seed_key(db_path, VALID_TOKEN)
    # 缺失
    r = client.get("/v1/models")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"
    # 错误 Key
    r = client.get("/v1/models", headers=auth_header("emg_" + "x" * 40))
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"
    # 非 emg_ 前缀
    r = client.get("/v1/models", headers=auth_header("sk-something"))
    assert r.status_code == 401


def test_models_disabled_and_expired(client):
    db_path = client.cfg.database.path
    tok_disabled = "emg_" + "B2c3D4e5" + "DisabledToken00000000000000"
    kid = seed_key(db_path, tok_disabled)
    tok_expired = "emg_" + "C3d4E5f6" + "ExpiredToken00000000000000"
    seed_key(db_path, tok_expired,
             expires_at=int((time.time() - 60) * 1000))

    import sqlite3
    con = sqlite3.connect(str(db_path))
    con.execute("UPDATE api_keys SET enabled=0 WHERE id=?", (kid,))
    con.commit()
    con.close()

    r = client.get("/v1/models", headers=auth_header(tok_disabled))
    assert r.status_code == 401 and r.json()["error"]["code"] == "key_disabled"

    r = client.get("/v1/models", headers=auth_header(tok_expired))
    assert r.status_code == 401 and r.json()["error"]["code"] == "key_expired"


def test_models_passthrough_with_upstream_auth(client):
    """正确 Key → 上游 /v1/models 透传；fake upstream 校验了网关替换后的 Authorization。"""
    db_path = client.cfg.database.path
    seed_key(db_path, VALID_TOKEN)
    r = client.get("/v1/models", headers=auth_header(VALID_TOKEN))
    assert r.status_code == 200
    assert r.json() == MODELS_PAYLOAD
    # last_used_at 已由 detached task 更新（等待后台任务落地）
    import sqlite3
    con = sqlite3.connect(str(db_path))
    row = con.execute("SELECT last_used_at FROM api_keys WHERE key_hash=?",
                      (__import__("hashlib").sha256(VALID_TOKEN.encode()).hexdigest(),)).fetchone()
    con.close()
    deadline = time.time() + 5
    while row[0] is None and time.time() < deadline:
        time.sleep(0.05)
        con = sqlite3.connect(str(db_path))
        row = con.execute("SELECT last_used_at FROM api_keys WHERE key_hash=?",
                          (__import__("hashlib").sha256(VALID_TOKEN.encode()).hexdigest(),)).fetchone()
        con.close()
    assert row[0] is not None


def test_chat_completions_now_proxied(seeded):
    """Phase 4 起 chat 已是正式代理：空 body 走最小校验返回 400。"""
    r = seeded[0].post("/v1/chat/completions", headers=seeded[1], json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_messages"


def test_unknown_route_envelope(client):
    r = client.get("/nope", headers=auth_header("emg_whatever"))
    assert r.status_code == 404
    assert set(r.json()["error"].keys()) >= {"message", "type", "param", "code"}
