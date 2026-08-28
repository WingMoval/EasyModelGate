"""v0.1.1 Task 3 集成测试：API Keys Admin API + 全流程 + Public/CLI 回归。"""
from __future__ import annotations

import io
import sys
import time

import pytest
from conftest import VALID_TOKEN

from easymodelgate import cli

PW = "synthetic-adm1n-pw-123"
ORIGIN = "http://testserver"


def _write_cfg(tmp_path, db_path) -> str:
    p = tmp_path / "adm.toml"
    p.write_text(
        '[server]\nhost = "127.0.0.1"\nport = 3000\n\n'
        f'[database]\npath = "{db_path}"\n\n'
        '[upstream]\nbase_url = "http://127.0.0.1:8999"\napi_key_file = ""\n',
        encoding="utf-8")
    return str(p)


@pytest.fixture()
def admin_client(client, monkeypatch, tmp_path):
    cfg_path = _write_cfg(tmp_path, client.cfg.database.path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(PW + "\n"))
    assert cli.main(["--config", cfg_path, "admin", "init",
                     "--password-stdin"]) == 0
    assert client.post("/admin/api/auth/login", json={"password": PW},
                       headers={"Origin": ORIGIN}).status_code == 200
    client.cfg_path = cfg_path
    return client


def H():
    return {"Origin": ORIGIN}


def mk_user(ac, name="alice"):
    r = ac.post("/admin/api/users", json={"username": name}, headers=H())
    assert r.status_code == 201
    return r.json()["id"]


def mk_key(ac, user_id, **kw):
    body = {"user_id": user_id, **kw}
    r = ac.post("/admin/api/keys", json=body, headers=H())
    assert r.status_code == 201, r.text
    return r.json()


# ---------- 列表 / 创建 / 详情 ----------

def test_list_empty(admin_client):
    assert admin_client.get("/admin/api/keys").json() == {"items": []}


def test_create_full_key_once(admin_client):
    uid = mk_user(admin_client)
    created = mk_key(admin_client, uid, name="laptop", rpm=5,
                     token_limit=1000)
    full = created["api_key"]
    key = created["key"]
    assert full.startswith("emg_") and len(full) > 20            # 一次性完整 Key
    assert key["masked_key"] == f"{key['key_prefix'][:7]}****{key['key_prefix'][-4:]}" or "****" in key["masked_key"]
    assert key["rpm"] == 5 and key["token_limit"] == 1000
    assert key["username"] == "alice" and key["token_used"] == 0
    assert key["expires_at"] is None and key["last_used_at"] is None
    # 其它出口永不再现完整 Key
    assert full not in admin_client.get("/admin/api/keys").text
    assert full not in admin_client.get(f"/admin/api/keys/{key['id']}").text


def test_get_never_leaks_secrets(admin_client):
    uid = mk_user(admin_client)
    kid = mk_key(admin_client, uid)["key"]["id"]
    for r in (admin_client.get("/admin/api/keys"),
              admin_client.get(f"/admin/api/keys/{kid}")):
        assert r.status_code == 200
        assert "key_hash" not in r.text
        for item in ([r.json()] if "items" not in r.json()
                     else r.json()["items"]):
            assert set(item.keys()) == {
                "id", "user_id", "username", "name", "key_prefix",
                "masked_key", "enabled", "rpm", "token_used", "token_limit",
                "expires_at", "last_used_at"}


def test_expires_in_days(admin_client):
    uid = mk_user(admin_client)
    key = mk_key(admin_client, uid, expires_in_days=30)["key"]
    expected = time.time() * 1000 + 30 * 86_400_000
    assert abs(key["expires_at"] - expected) < 60_000


def test_create_user_not_found(admin_client):
    r = admin_client.post("/admin/api/keys", json={"user_id": 999},
                          headers=H())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "user_not_found"


def test_create_validation(admin_client):
    uid = mk_user(admin_client)
    r = admin_client.post("/admin/api/keys", json={"user_id": "abc"},
                          headers=H())
    assert r.status_code == 422
    r = admin_client.post("/admin/api/keys", json={"user_id": uid, "rpm": 1.5},
                          headers=H())
    assert r.status_code == 422
    r = admin_client.post("/admin/api/keys", json={"user_id": uid, "rotate": True},
                          headers=H())
    assert r.status_code == 422          # extra 拒绝


def test_get_not_found(admin_client):
    r = admin_client.get("/admin/api/keys/999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "key_not_found"


def test_deterministic_ordering(admin_client):
    uid = mk_user(admin_client)
    ids = [mk_key(admin_client, uid, name=f"k{i}")["key"]["id"] for i in range(3)]
    items = admin_client.get("/admin/api/keys").json()["items"]
    assert [k["id"] for k in items] == sorted(ids)


# ---------- enable / disable ----------

def test_enable_disable(admin_client):
    uid = mk_user(admin_client)
    kid = mk_key(admin_client, uid)["key"]["id"]
    r = admin_client.post(f"/admin/api/keys/{kid}/disable", headers=H())
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = admin_client.post(f"/admin/api/keys/{kid}/enable", headers=H())
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert admin_client.get("/admin/api/keys/999/disable",
                            headers=H()).status_code == 405
    r = admin_client.post("/admin/api/keys/999/disable", headers=H())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "key_not_found"


# ---------- PATCH limits：KEEP / CLEAR / SET ----------

def test_limits_semantics(admin_client):
    uid = mk_user(admin_client)
    kid = mk_key(admin_client, uid, rpm=5, token_limit=100)["key"]["id"]
    # SET 单字段，另一字段 KEEP
    r = admin_client.patch(f"/admin/api/keys/{kid}/limits",
                           json={"rpm": 60}, headers=H())
    assert r.status_code == 200
    assert r.json()["rpm"] == 60 and r.json()["token_limit"] == 100
    # 显式 null = CLEAR
    r = admin_client.patch(f"/admin/api/keys/{kid}/limits",
                           json={"rpm": None}, headers=H())
    assert r.json()["rpm"] is None and r.json()["token_limit"] == 100
    # token_limit SET + rpm 保持 None
    r = admin_client.patch(f"/admin/api/keys/{kid}/limits",
                           json={"token_limit": None}, headers=H())
    assert r.json()["rpm"] is None and r.json()["token_limit"] is None
    # 双字段同时 SET，响应即最新完整 metadata
    r = admin_client.patch(f"/admin/api/keys/{kid}/limits",
                           json={"rpm": 10, "token_limit": 999}, headers=H())
    assert r.json()["rpm"] == 10 and r.json()["token_limit"] == 999
    assert r.json()["id"] == kid
    # 空 body = 全 KEEP
    r = admin_client.patch(f"/admin/api/keys/{kid}/limits", json={},
                           headers=H())
    assert r.json()["rpm"] == 10 and r.json()["token_limit"] == 999
    # 校验（"60"→60 宽松转换与 CLI argparse 语义一致，故用非数字串测 422）
    r = admin_client.patch(f"/admin/api/keys/{kid}/limits",
                           json={"rpm": "many"}, headers=H())
    assert r.status_code == 422
    r = admin_client.patch(f"/admin/api/keys/{kid}/limits",
                           json={"rpm": 1.5}, headers=H())
    assert r.status_code == 422
    r = admin_client.patch(f"/admin/api/keys/{kid}/limits",
                           json={"rotate": True}, headers=H())
    assert r.status_code == 422
    r = admin_client.patch("/admin/api/keys/999/limits", json={"rpm": 1},
                           headers=H())
    assert r.status_code == 404


# ---------- 认证 / CSRF ----------

def test_unauthenticated(client):
    assert client.get("/admin/api/keys").status_code == 401
    assert client.get("/admin/api/keys",
                      headers={"Authorization": f"Bearer {VALID_TOKEN}"}
                      ).status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("post", "/admin/api/keys", {"user_id": 1}),
    ("post", "/admin/api/keys/1/disable", None),
    ("post", "/admin/api/keys/1/enable", None),
    ("patch", "/admin/api/keys/1/limits", {"rpm": 1}),
])
def test_csrf_rejection(admin_client, method, path, body):
    r = getattr(admin_client, method)(path, json=body)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_origin_invalid"
    r = getattr(admin_client, method)(path, json=body,
                                      headers={"Origin": "https://evil.test"})
    assert r.status_code == 403


# ---------- §51 全流程 + §41/§42 Public 回归 ----------

def test_full_flow_admin_key_public_compatibility(admin_client):
    # 1-4: user + key via Admin API
    uid = mk_user(admin_client, "flowuser")
    created = mk_key(admin_client, uid, name="flow", rpm=None,
                     token_limit=None)
    full, kid = created["api_key"], created["key"]["id"]
    # 6-10: 列表/详情/limits
    assert admin_client.get("/admin/api/users").json()["items"][0]["id"] == uid
    assert admin_client.get("/admin/api/keys").json()["items"][0]["id"] == kid
    assert admin_client.get(f"/admin/api/keys/{kid}").status_code == 200
    assert admin_client.patch(f"/admin/api/keys/{kid}/limits",
                              json={"rpm": 30}, headers=H()).json()["rpm"] == 30
    assert admin_client.patch(f"/admin/api/keys/{kid}/limits",
                              json={"token_limit": 5000},
                              headers=H()).json()["token_limit"] == 5000
    bearer = {"Authorization": f"Bearer {full}"}
    # 15: Admin 创建的 Key 与 CLI 创建的 Key 生产行为一致
    assert admin_client.get("/v1/models", headers=bearer).status_code == 200
    # 11: disable key → Public 拒绝（现有语义 key_disabled）
    admin_client.post(f"/admin/api/keys/{kid}/disable", headers=H())
    r = admin_client.get("/v1/models", headers=bearer)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "key_disabled"
    # 12: enable → 恢复
    admin_client.post(f"/admin/api/keys/{kid}/enable", headers=H())
    assert admin_client.get("/v1/models", headers=bearer).status_code == 200
    # 13: disable user → 其 Key 403 user_disabled（现有语义不变）
    admin_client.post(f"/admin/api/users/{uid}/disable", headers=H())
    r = admin_client.get("/v1/models", headers=bearer)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "user_disabled"
    # 14: enable user → 恢复
    admin_client.post(f"/admin/api/users/{uid}/enable", headers=H())
    assert admin_client.get("/v1/models", headers=bearer).status_code == 200
    assert admin_client.get("/health").status_code == 200


# ---------- §43 CLI ↔ Admin 数据互通 ----------

def test_cli_admin_data_interoperability(admin_client, capsys, monkeypatch):
    # Admin 创建 → CLI 可见
    uid = mk_user(admin_client, "interop")
    kid = mk_key(admin_client, uid, name="from-admin")["key"]["id"]
    assert cli.main(["--config", admin_client.cfg_path, "user", "list"]) == 0
    out = capsys.readouterr().out
    assert "interop" in out
    assert cli.main(["--config", admin_client.cfg_path, "key", "list"]) == 0
    assert "from-admin" in capsys.readouterr().out
    # CLI 创建 → Admin API 可见
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))     # 防误入交互
    assert cli.main(["--config", admin_client.cfg_path, "key", "create",
                     "--user", "interop", "--name", "from-cli"]) == 0
    items = admin_client.get("/admin/api/keys").json()["items"]
    names = {k["name"] for k in items}
    assert {"from-admin", "from-cli"} <= names
    assert {k["username"] for k in items} == {"interop"}
