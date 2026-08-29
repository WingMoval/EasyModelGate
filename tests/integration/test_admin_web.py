"""v0.1.1 Task 5 集成测试：Admin Web UI (Login + Layout + Protected Pages)。"""
from __future__ import annotations

import io
import sys

import pytest
from conftest import VALID_TOKEN

from easymodelgate import cli
from easymodelgate.services import admin_auth_service
from easymodelgate.core.admin_session import SessionStore

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
    client.cfg_path = cfg_path  # type: ignore[attr-defined]
    return client


# ---------- Login page ----------

def test_login_page_200(client):
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "EasyModelGate" in r.text
    assert 'type="password"' in r.text
    assert "Sign In" in r.text


def test_login_page_shows_uninitialized_message(client, monkeypatch, tmp_path):
    """未初始化时登录页应显示提示信息。"""
    cfg_path = _write_cfg(tmp_path, client.cfg.database.path)
    # 不执行 admin init
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "Admin not initialized" in r.text
    assert "admin init" in r.text


def test_login_page_redirect_when_logged_in(admin_client):
    """已登录访问 login 页应重定向到 /admin。"""
    r = admin_client.get("/admin/login", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin"


# ---------- Protected HTML pages (unauthenticated) ----------

@pytest.mark.parametrize("path", [
    "/admin",
    "/admin/users",
    "/admin/keys",
    "/admin/usage",
    "/admin/system",
])
def test_protected_html_redirects_to_login(client, path):
    """未登录访问受保护页面应 303 重定向到 login。"""
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/admin/login?redirect=")


# ---------- Protected HTML pages (authenticated) ----------

@pytest.mark.parametrize("path", [
    "/admin",
    "/admin/users",
    "/admin/keys",
    "/admin/usage",
    "/admin/system",
])
def test_protected_html_200_when_logged_in(admin_client, path):
    """已登录访问受保护页面应返回 200。"""
    r = admin_client.get(path)
    assert r.status_code == 200
    assert "EasyModelGate" in r.text


# ---------- Login flow ----------

def test_login_success(admin_client):
    """正确密码登录成功，设置 cookie。"""
    # admin_client fixture 已完成登录，验证 cookie 存在
    assert "emg_admin_session" in admin_client.cookies


def test_login_wrong_password(admin_client):
    """错误密码返回错误页面/状态。"""
    # 先登出
    admin_client.post("/admin/logout", headers={"Origin": ORIGIN}, follow_redirects=False)
    # 尝试错误密码
    r = admin_client.post("/admin/api/auth/login",
                          json={"password": "wrong"},
                          headers={"Origin": ORIGIN})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_admin_credentials"


def test_logout(admin_client):
    """登出清除 cookie 并重定向到 login。"""
    r = admin_client.post("/admin/logout", headers={"Origin": ORIGIN},
                          follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    # 验证 cookie 被删除
    assert "emg_admin_session" not in r.cookies


def test_expired_session_redirects(admin_client):
    """过期 session 访问受保护页面重定向到 login。"""
    store: SessionStore = admin_client.app.state.admin_sessions
    # 手动使 session 过期
    for sid, sess in list(store._sessions.items()):
        # Session is a dataclass with fields: session_id, created_at, expires_at, last_seen
        sess.expires_at = 0
        break
    r = admin_client.get("/admin", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/admin/login?redirect=")


# ---------- Static files ----------

def test_static_css(admin_client):
    r = admin_client.get("/admin/static/admin.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "")


def test_static_js(admin_client):
    r = admin_client.get("/admin/static/admin.js")
    assert r.status_code == 200
    assert "javascript" in r.headers.get("content-type", "")


def test_static_404(admin_client):
    r = admin_client.get("/admin/static/nonexistent.css")
    assert r.status_code == 404


# ---------- Overview page content ----------

def test_overview_page_shows_cards(admin_client):
    r = admin_client.get("/admin")
    assert r.status_code == 200
    assert "Overview" in r.text
    assert "Gateway" in r.text
    assert "Backend" in r.text
    assert "Requests Today" in r.text
    assert "Total Tokens" in r.text
    assert "Success Rate" in r.text
    assert "Avg TTFT" in r.text
    assert "Active Keys" in r.text


# ---------- System page content ----------

def test_system_page_shows_info(admin_client):
    r = admin_client.get("/admin/system")
    assert r.status_code == 200
    assert "System" in r.text
    assert "Version" in r.text
    assert "Gateway" in r.text
    assert "Backend" in r.text
    assert "Database" in r.text
    assert "Uptime" in r.text
    assert "Started At" in r.text


# ---------- Users/Keys/Usage page skeletons ----------

def test_users_page_skeleton(admin_client):
    r = admin_client.get("/admin/users")
    assert r.status_code == 200
    assert "Users" in r.text
    assert "Create User" in r.text


def test_keys_page_skeleton(admin_client):
    r = admin_client.get("/admin/keys")
    assert r.status_code == 200
    assert "API Keys" in r.text
    assert "Create Key" in r.text


def test_usage_page_skeleton(admin_client):
    r = admin_client.get("/admin/usage")
    assert r.status_code == 200
    assert "Usage" in r.text


# ---------- Security: no secrets in HTML ----------

def test_no_session_id_in_html(admin_client):
    r = admin_client.get("/admin")
    assert "emg_admin_session" not in r.text
    # session ID 值不应出现在 HTML 中
    for cookie_val in admin_client.cookies.values():
        assert cookie_val not in r.text


def test_no_admin_credential_in_html(admin_client):
    r = admin_client.get("/admin")
    assert PW not in r.text
    assert "admin password" not in r.text.lower()


# ---------- Login JS error handling ----------

def test_login_js_error_handling(client):
    """登录页面包含错误处理 JS。"""
    r = client.get("/admin/login")
    assert "formatLoginError" in r.text
    assert "admin_not_initialized" in r.text
    assert "invalid_admin_credentials" in r.text
    assert "admin_login_rate_limited" in r.text
    assert "csrf_origin_invalid" in r.text