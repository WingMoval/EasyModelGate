"""v0.1.1 Task 3 集成测试：Users Admin API。"""
from __future__ import annotations

import io
import sys

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
    r = client.post("/admin/api/auth/login", json={"password": PW},
                    headers={"Origin": ORIGIN})
    assert r.status_code == 200
    client._origin = ORIGIN
    return client


def H(client, with_origin=True):
    return {"Origin": ORIGIN} if with_origin else {}


def create_user(client, name, **kw):
    body = {"username": name, **kw}
    return client.post("/admin/api/users", json=body, headers=H(client))


# ---------- 列表 / 创建 ----------

def test_list_empty(admin_client):
    r = admin_client.get("/admin/api/users")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_create_and_list(admin_client):
    r = create_user(admin_client, "alice", display_name="Alice", note="n1")
    assert r.status_code == 201
    body = r.json()
    assert set(body.keys()) == {"id", "username", "display_name", "note",
                                "enabled", "created_at"}
    assert body["username"] == "alice" and body["enabled"] is True
    assert isinstance(body["created_at"], int) and body["created_at"] > 10**12
    items = admin_client.get("/admin/api/users").json()["items"]
    assert [u["username"] for u in items] == ["alice"]


def test_create_duplicate_409(admin_client):
    assert create_user(admin_client, "alice").status_code == 201
    r = create_user(admin_client, "alice")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "user_already_exists"
    assert "SQLITE" not in r.text.upper() and "UNIQUE" not in r.text.upper()


def test_deterministic_ordering(admin_client):
    for name in ("carol", "alice", "bob"):
        assert create_user(admin_client, name).status_code == 201
    items = admin_client.get("/admin/api/users").json()["items"]
    assert [u["id"] for u in items] == sorted(u["id"] for u in items)
    assert [u["username"] for u in items] == ["carol", "alice", "bob"]


def test_create_validation(admin_client):
    r = admin_client.post("/admin/api/users", json={}, headers=H(admin_client))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    r = admin_client.post("/admin/api/users", json={"username": 5},
                          headers=H(admin_client))
    assert r.status_code == 422
    r = admin_client.post("/admin/api/users", json={"username": "x", "role": "admin"},
                          headers=H(admin_client))   # extra 字段拒绝
    assert r.status_code == 422
    r = admin_client.post("/admin/api/users", content=b"nope",
                          headers={**H(admin_client),
                                   "Content-Type": "application/json"})
    assert r.status_code == 400


# ---------- enable / disable ----------

def test_enable_disable_roundtrip(admin_client):
    uid = create_user(admin_client, "alice").json()["id"]
    r = admin_client.post(f"/admin/api/users/{uid}/disable", headers=H(admin_client))
    assert r.status_code == 200 and r.json()["enabled"] is False
    items = admin_client.get("/admin/api/users").json()["items"]
    assert items[0]["enabled"] is False
    r = admin_client.post(f"/admin/api/users/{uid}/enable", headers=H(admin_client))
    assert r.status_code == 200 and r.json()["enabled"] is True


def test_enable_disable_not_found(admin_client):
    for path in ("/admin/api/users/999/disable", "/admin/api/users/999/enable"):
        r = admin_client.post(path, headers=H(admin_client))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "user_not_found"
    r = admin_client.post("/admin/api/users/abc/disable", headers=H(admin_client))
    assert r.status_code == 400   # 非整数 id → 统一信封 400


# ---------- 认证 / CSRF ----------

def test_unauthenticated(client):
    r = client.get("/admin/api/users")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "admin_auth_required"
    r = client.get("/admin/api/users",
                   headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert r.status_code == 401   # emg Bearer 无 Admin 权限


@pytest.mark.parametrize("method,path,body", [
    ("post", "/admin/api/users", {"username": "x"}),
    ("post", "/admin/api/users/1/disable", None),
])
def test_csrf_rejection(admin_client, method, path, body):
    r = getattr(admin_client, method)(path, json=body)          # 无 Origin
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_origin_invalid"
    r = getattr(admin_client, method)(path, json=body,
                                      headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_get_users_with_admin_cookie(admin_client):
    assert admin_client.get("/admin/api/users").status_code == 200


# ---------- 并发唯一性（确定性竞态模拟） ----------

async def test_concurrent_duplicate_maps_to_conflict(tmp_path, monkeypatch):
    """先查后插窗口内竞态：预检被绕过（模拟 stale read）时，
    UNIQUE 冲突必须映射为 UserAlreadyExists，而非 IntegrityError/500。"""
    from easymodelgate.db.database import Database
    from easymodelgate.services import user_service

    db = await Database(tmp_path / "race.db").connect()
    try:
        await user_service.create_user(db, "alice")
        monkeypatch.setattr(user_service.dao, "get_user_by_username",
                            lambda *a, **k: _none_coro())
        with pytest.raises(user_service.UserAlreadyExists):
            await user_service.create_user(db, "alice")
    finally:
        await db.close()


async def _none_coro():
    return None
