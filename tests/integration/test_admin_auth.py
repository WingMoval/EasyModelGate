"""v0.1.1 Task 2 集成测试：admin init CLI + Admin Auth API + 隔离 + CSRF。

全部临时 SQLite / 临时 config / synthetic 密码；无真实等待。
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys

import pytest
from conftest import VALID_TOKEN

from easymodelgate import cli
from easymodelgate.core.admin_session import SESSION_COOKIE_NAME
from easymodelgate.routers.admin import build_admin_api_router  # noqa: F401

PW = "synthetic-adm1n-pw-123"
ORIGIN = "http://testserver"          # TestClient base_url 同源
FAKE_PW = "synthetic-wrong-pw-999"


def _write_cfg(tmp_path, db_path) -> str:
    p = tmp_path / "admin.toml"
    p.write_text(
        '[server]\nhost = "127.0.0.1"\nport = 3000\n\n'
        f'[database]\npath = "{db_path}"\n\n'
        '[upstream]\nbase_url = "http://127.0.0.1:8999"\napi_key_file = ""\n',
        encoding="utf-8")
    return str(p)


def _cli_admin_init(cfg_path, password, monkeypatch=None, stdin=None):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return cli.main(["--config", cfg_path, "admin", "init", "--password-stdin"])


def _login(client, password=PW, origin=ORIGIN, headers_extra=None):
    headers = {}
    if origin is not None:
        headers["Origin"] = origin
    headers.update(headers_extra or {})
    return client.post("/admin/api/auth/login",
                       json={"password": password}, headers=headers)


@pytest.fixture()
def admin_client(client, monkeypatch, tmp_path, capsys):
    """已登录测试栈：真实 CLI admin init → TestClient login。"""
    cfg_path = _write_cfg(tmp_path, client.cfg.database.path)
    assert _cli_admin_init(cfg_path, PW, monkeypatch, stdin=PW + "\n") == 0
    r = _login(client)
    assert r.status_code == 200, r.text
    return client


# ---------- CLI ----------

def test_cli_admin_init_and_duplicate(tmp_path, monkeypatch, capsys):
    cfg_path = _write_cfg(tmp_path, tmp_path / "cli.db")
    assert _cli_admin_init(cfg_path, PW, monkeypatch, stdin=PW + "\n") == 0
    out = capsys.readouterr().out
    assert "Admin initialized." in out
    assert PW not in out                       # 不回显密码
    assert _cli_admin_init(cfg_path, "newpw", monkeypatch,
                           stdin="newpw\n") == 1
    assert "Admin already initialized." in capsys.readouterr().out
    # 库内非明文
    con = sqlite3.connect(str(tmp_path / "cli.db"))
    raw = con.execute("SELECT value_json FROM settings "
                      "WHERE key='admin.auth'").fetchone()[0]
    con.close()
    assert PW not in raw and "scrypt" in raw


def test_cli_admin_init_empty_password(tmp_path, monkeypatch, capsys):
    cfg_path = _write_cfg(tmp_path, tmp_path / "cli.db")
    assert _cli_admin_init(cfg_path, "", monkeypatch, stdin="\n") == 1
    assert "不能为空" in capsys.readouterr().out


def test_cli_admin_init_interactive_getpass(tmp_path, monkeypatch, capsys):
    cfg_path = _write_cfg(tmp_path, tmp_path / "cli2.db")
    import getpass
    calls = []

    def fake_getpass(prompt=""):
        calls.append(prompt)
        return PW
    monkeypatch.setattr(getpass, "getpass", fake_getpass)
    assert cli.main(["--config", cfg_path, "admin", "init"]) == 0
    out = capsys.readouterr().out
    assert PW not in out and "Admin initialized." in out
    # 不一致拒绝
    cfg_path2 = _write_cfg(tmp_path, tmp_path / "cli3.db")
    seq = iter([PW, "different"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(seq))
    assert cli.main(["--config", cfg_path2, "admin", "init"]) == 1
    assert "不一致" in capsys.readouterr().out


# ---------- Login / Me / Logout ----------

def test_login_uninitialized_fail_closed(client):
    r = _login(client, origin=ORIGIN)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "admin_not_initialized"


def test_login_wrong_password(admin_client):
    r = _login(admin_client, password=FAKE_PW)
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "invalid_admin_credentials"
    assert PW not in json.dumps(r.json())


def test_login_bad_body(admin_client):
    r = admin_client.post("/admin/api/auth/login", json={},
                          headers={"Origin": ORIGIN})
    assert r.status_code == 422
    r = admin_client.post("/admin/api/auth/login", content=b"not json",
                          headers={"Origin": ORIGIN,
                                   "Content-Type": "application/json"})
    assert r.status_code == 400


def test_me_with_and_without_session(admin_client):
    r = admin_client.get("/admin/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"authenticated": True}     # 不含 session id/hash 等
    admin_client.cookies.clear()                   # 无 cookie → 未认证
    r = admin_client.get("/admin/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "admin_auth_required"
    r = admin_client.get("/admin/api/auth/me",
                         headers={"Cookie": f"{SESSION_COOKIE_NAME}=forged"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "admin_auth_required"


def test_login_response_body_minimal(admin_client):
    r = _login(admin_client)
    assert set(r.json().keys()) == {"authenticated"}
    assert admin_client.cookies.get(SESSION_COOKIE_NAME) is not None


def test_logout_idempotent_and_cookie_cleared(admin_client):
    r = admin_client.post("/admin/api/auth/logout", headers={"Origin": ORIGIN})
    assert r.status_code == 200
    assert admin_client.get("/admin/api/auth/me").status_code == 401
    sc = r.headers["set-cookie"]
    assert "Max-Age=0" in sc or "max-age=0" in sc.lower()
    r2 = admin_client.post("/admin/api/auth/logout", headers={"Origin": ORIGIN})
    assert r2.status_code == 200                    # 幂等


def test_session_expired(admin_client):
    store = admin_client.app.state.admin_sessions
    assert store._sessions
    for s in store._sessions.values():
        s.expires_at = store._now() - 1
    r = admin_client.get("/admin/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "admin_session_expired"


# ---------- 登录限速 ----------

def test_login_rate_limit_and_success_reset(tmp_path, monkeypatch, client):
    cfg_path = _write_cfg(tmp_path, client.cfg.database.path)
    assert _cli_admin_init(cfg_path, PW, monkeypatch, stdin=PW + "\n") == 0
    for _ in range(4):
        assert _login(client, password=FAKE_PW).status_code == 401
    assert _login(client, password=PW).status_code == 200   # 成功清零
    for _ in range(4):
        assert _login(client, password=FAKE_PW).status_code == 401
    assert _login(client, password=FAKE_PW).status_code == 401   # 第 5 次失败
    r = _login(client, password=PW)                    # 此后封锁（含正确密码）
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "admin_login_rate_limited"


# ---------- CSRF / Origin ----------

def test_csrf_origin_matrix(admin_client):
    r = admin_client.post("/admin/api/auth/logout")     # 无 Origin
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_origin_invalid"
    r = admin_client.post("/admin/api/auth/logout",
                          headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = admin_client.get("/admin/api/auth/me")          # GET 免 CSRF
    assert r.status_code == 200


def test_csrf_applies_to_login(client):
    r = client.post("/admin/api/auth/login", json={"password": "x"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_origin_invalid"


# ---------- 双认证体系隔离 ----------

def test_emg_key_cannot_admin(admin_client):
    from conftest import seed_key
    seed_key(admin_client.cfg.database.path, VALID_TOKEN)
    admin_client.cookies.clear()   # 去掉 admin session → 仅带 Bearer emg_ Key
    r = admin_client.get("/admin/api/auth/me",
                         headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "admin_auth_required"


def test_admin_cookie_cannot_call_public_api(admin_client):
    admin_client.cookies.clear()
    r = admin_client.get("/v1/models")      # 只有 admin cookie，无 Bearer
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"
    # cookie 不授予模型调用；public /health 不受 admin 认证影响
    assert admin_client.get("/health").status_code == 200


# ---------- 日志安全 ----------

def test_no_secrets_in_logs(admin_client, caplog):
    import logging
    with caplog.at_level(logging.DEBUG, logger="easymodelgate"):
        _login(admin_client, password=FAKE_PW)
        admin_client.get("/admin/api/auth/me")
    blob = caplog.text + admin_client.get(
        "/admin/api/auth/me").text + _login(admin_client).text
    sid = admin_client.cookies.get(SESSION_COOKIE_NAME)
    assert FAKE_PW not in blob and PW not in blob
    assert sid not in blob
    con = sqlite3.connect(str(admin_client.cfg.database.path))
    rows = con.execute("SELECT value_json FROM settings").fetchall()
    con.close()
    for (v,) in rows:
        assert PW not in v and FAKE_PW not in v
