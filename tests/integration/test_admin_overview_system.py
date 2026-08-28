"""v0.1.1 Task 4 集成测试：Overview + System Admin API。"""
from __future__ import annotations

import io
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from conftest import VALID_TOKEN

from easymodelgate import __version__, cli
from test_admin_usage import ORIGIN, PW, TZ, _midnight, seed_log, summary


@pytest.fixture()
def admin_client(client, monkeypatch, tmp_path):
    p = tmp_path / "adm.toml"
    p.write_text(
        '[server]\nhost = "127.0.0.1"\nport = 3000\n\n'
        f'[database]\npath = "{client.cfg.database.path}"\n\n'
        '[upstream]\nbase_url = "http://127.0.0.1:8999"\napi_key_file = ""\n',
        encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO(PW + "\n"))
    assert cli.main(["--config", str(p), "admin", "init",
                     "--password-stdin"]) == 0
    assert client.post("/admin/api/auth/login", json={"password": PW},
                       headers={"Origin": ORIGIN}).status_code == 200
    return client


def _kill_backend(admin):
    """把 upstream client 指向不可达端口（不真实重启后端）。"""
    admin.app.state.upstream.client = httpx.AsyncClient(
        base_url="http://127.0.0.1:1")


# ---------- Overview ----------

def test_overview_empty(admin_client):
    r = admin_client.get("/admin/api/overview")
    assert r.status_code == 200
    j = r.json()
    assert j["gateway"] == {"status": "healthy"}
    assert j["backend"] == {"status": "healthy"}       # fake 上游在线
    assert j["active_keys"] == 0
    t = j["today"]
    assert t["requests"] == 0 and t["total_tokens"] == 0
    assert t["success_rate"] == 0.0


def test_overview_metrics_and_parity(admin_client):
    u = admin_client.post("/admin/api/users", json={"username": "alice"},
                          headers={"Origin": ORIGIN}).json()["id"]
    k = admin_client.post("/admin/api/keys", json={"user_id": u},
                          headers={"Origin": ORIGIN}).json()["key"]["id"]
    k2 = admin_client.post("/admin/api/keys", json={"user_id": u},
                           headers={"Origin": ORIGIN}).json()["key"]["id"]
    admin_client.post(f"/admin/api/keys/{k2}/disable",
                      headers={"Origin": ORIGIN})
    mid = _midnight()
    seed_log(admin_client.cfg.database.path, started_at=mid + 3_600_000,
             model="mA", user_id=u, api_key_id=k)
    seed_log(admin_client.cfg.database.path, started_at=mid - 3_600_000,
             model="mA", user_id=u, api_key_id=k)   # 昨天，不计入 today
    t = admin_client.get("/admin/api/overview").json()["today"]
    assert t["requests"] == 1 and t["success"] == 1 and t["failed"] == 0
    assert t["total_tokens"] == 15
    assert admin_client.get("/admin/api/overview").json()["active_keys"] == 1
    # OVERVIEW_USAGE_PARITY：与 usage summary?period=today 完全一致
    s = summary(admin_client, period="today").json()["summary"]
    assert t == s


def test_overview_backend_unhealthy(admin_client):
    _kill_backend(admin_client)
    r = admin_client.get("/admin/api/overview")
    assert r.status_code == 200                    # 不 500
    assert r.json()["backend"] == {"status": "unhealthy"}


# ---------- System ----------

def test_system_fields(admin_client):
    r = admin_client.get("/admin/api/system")
    assert r.status_code == 200
    j = r.json()
    assert j["version"] == __version__             # 真实包版本（不硬编码）
    assert j["gateway"] == {"status": "healthy"}
    assert j["backend"] == {"status": "healthy"}
    assert j["database"] == {"status": "healthy"}
    assert j["uptime_seconds"] >= 0
    assert j["started_at"] <= int(time.time() * 1000)
    dt = datetime.fromtimestamp(j["started_at"] / 1000, ZoneInfo(TZ))
    assert dt.year >= 2025


def test_system_no_db_path_leak(admin_client):
    r = admin_client.get("/admin/api/system")
    assert str(admin_client.cfg.database.path) not in r.text
    assert "/tmp" not in r.text and ".db" not in r.text


def test_system_backend_unhealthy(admin_client):
    _kill_backend(admin_client)
    r = admin_client.get("/admin/api/system")
    assert r.status_code == 200
    assert r.json()["backend"] == {"status": "unhealthy"}
    assert r.json()["database"] == {"status": "healthy"}


# ---------- Auth（全部新端点） ----------

@pytest.mark.parametrize("path", [
    "/admin/api/overview", "/admin/api/system",
    "/admin/api/usage/summary", "/admin/api/usage/timeseries",
    "/admin/api/requests"])
def test_auth_required(client, path):
    r = client.get(path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "admin_auth_required"
    r = client.get(path, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert r.status_code == 401                    # emg Bearer 无效
    # GET 不需要 Origin：登录后的 admin_client 不带 Origin 也可读（其余测试覆盖）
