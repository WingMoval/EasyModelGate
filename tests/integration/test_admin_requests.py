"""v0.1.1 Task 4 集成测试：Recent Requests Admin API（隐私边界重点）。"""
from __future__ import annotations

import io
import sqlite3
import sys

import pytest
from conftest import wait_latest_log, wait_log_count

from easymodelgate import cli
from test_admin_usage import ORIGIN, PW, seed_log, summary

SECRET_PROMPT = "SENSITIVE_TEST_PROMPT_DO_NOT_EXPOSE"
SECRET_REPLY = "SENSITIVE_TEST_REPLY_DO_NOT_EXPOSE"
SECRET_IP = "203.0.113.77"
SECRET_ERRMSG = "SENSITIVE_UPSTREAM_BODY_DO_NOT_EXPOSE"


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


@pytest.fixture()
def ctx(admin_client):
    u = admin_client.post("/admin/api/users", json={"username": "alice"},
                          headers={"Origin": ORIGIN}).json()
    kr = admin_client.post("/admin/api/keys",
                           json={"user_id": u["id"], "name": "k1"},
                           headers={"Origin": ORIGIN}).json()
    return admin_client, u["id"], kr["key"]["id"], kr["api_key"]


def reqs(client, **params):
    return client.get("/admin/api/requests", params=params)


# ---------- 空 / 排序 / limit ----------

def test_empty(admin_client):
    r = reqs(admin_client)
    assert r.status_code == 200 and r.json() == {"items": []}


def test_latest_first_and_default_limit(ctx):
    admin, uid, kid, _ = ctx
    for i in range(60):
        seed_log(admin.cfg.database.path, started_at=1_700_000_000_000 + i,
                 model="m", user_id=uid, api_key_id=kid)
    j = reqs(admin).json()
    assert len(j["items"]) == 50                      # 默认 50
    ids = [it["id"] for it in j["items"]]
    assert ids == sorted(ids, reverse=True)           # id DESC 确定性


def test_limit_validation(ctx):
    admin, *_ = ctx
    assert reqs(admin, limit="201").json()["error"]["code"] == "invalid_limit"
    assert reqs(admin, limit="0").json()["error"]["code"] == "invalid_limit"
    assert reqs(admin, limit="-1").status_code == 400
    assert reqs(admin, limit="abc").json()["error"]["code"] == "invalid_request"
    for i in range(3):
        seed_log(admin.cfg.database.path, started_at=1_700_000_000_000 + i,
                 model="m", user_id=ctx[1], api_key_id=ctx[2])
    assert len(reqs(admin, limit=200).json()["items"]) == 3


# ---------- errors_only 与过滤 ----------

def test_errors_only_and_filters(ctx):
    admin, uid, kid, _ = ctx
    db = admin.cfg.database.path
    seed_log(db, started_at=1_700_000_000_001, model="mA", user_id=uid,
             api_key_id=kid)
    seed_log(db, started_at=1_700_000_000_002, model="mB", user_id=uid,
             api_key_id=kid, status=429, error_type="rate_limited",
             prompt=0, completion=0, total=0, cached=0)
    j = reqs(admin, errors_only="true").json()
    assert [it["model"] for it in j["items"]] == ["mB"]
    assert j["items"][0]["error_type"] == "rate_limited"
    assert [it["model"] for it in reqs(admin, model="mA").json()["items"]] == ["mA"]
    assert [it["model"] for it in reqs(admin, status_code=429).json()["items"]] == ["mB"]
    assert [it["model"] for it in reqs(admin, error_type="rate_limited").json()["items"]] == ["mB"]
    assert len(reqs(admin, user_id=uid).json()["items"]) == 2
    assert len(reqs(admin, key_id=kid).json()["items"]) == 2
    assert reqs(admin, errors_only="false").json()["items"].__len__() == 2


def test_filter_unknown_ids(ctx):
    admin, *_ = ctx
    assert reqs(admin, user_id="999").status_code == 404
    assert reqs(admin, user_id="999").json()["error"]["code"] == "user_not_found"
    assert reqs(admin, key_id="999").json()["error"]["code"] == "key_not_found"


# ---------- 真实流量：元数据完整 + 零内容泄漏 ----------

def test_real_traffic_privacy(ctx):
    admin, uid, kid, token = ctx
    r = admin.post("/v1/chat/completions",
                   headers={"Authorization": f"Bearer {token}"},
                   json={"model": "test-model",
                         "messages": [{"role": "user",
                                       "content": SECRET_PROMPT}]})
    assert r.status_code == 200
    row = wait_latest_log(admin.cfg.database.path)
    assert row["status_code"] == 200

    j = reqs(admin).json()
    assert len(j["items"]) == 1
    it = j["items"][0]
    assert set(it) == {
        "id", "request_id", "started_at", "finished_at", "user_id",
        "username", "api_key_id", "key_name", "masked_key", "model",
        "endpoint", "status_code", "upstream_status_code", "stream",
        "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens",
        "duration_ms", "queue_wait_ms", "upstream_duration_ms", "ttft_ms",
        "finish_reason", "error_type"}
    assert it["username"] == "alice" and it["key_name"] == "k1"
    assert "****" in it["masked_key"]
    assert it["status_code"] == 200 and it["error_type"] is None
    assert it["started_at"] == row["started_at"]      # Unix ms 契约
    # 内容 / 敏感字段零泄漏（全 JSON 文本扫描）
    for banned in (SECRET_PROMPT, SECRET_REPLY, token, "key_hash",
                   "messages", "prompt_text"):
        assert banned not in j.__repr__()
    assert token not in admin.get("/admin/api/requests").text


def test_never_select_ip_and_error_message(ctx):
    """client_ip / error_message 存于库中但绝不出现在 API。"""
    admin, uid, kid, _ = ctx
    con = sqlite3.connect(str(admin.cfg.database.path))
    con.execute(
        """INSERT INTO request_logs
             (request_id, user_id, api_key_id, model, endpoint, started_at,
              status_code, error_type, error_message, client_ip)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("r-x", uid, kid, "m", "/v1/chat/completions", 1, 502,
         "upstream_error", SECRET_ERRMSG, SECRET_IP))
    con.commit()
    con.close()
    j = reqs(admin).json()
    assert j["items"][0]["error_type"] == "upstream_error"
    assert SECRET_ERRMSG not in j.__repr__()
    assert SECRET_IP not in j.__repr__()


# ---------- Admin 调用不污染 Usage ----------

def test_admin_calls_not_counted(ctx):
    admin, uid, kid, _ = ctx
    seed_log(admin.cfg.database.path, started_at=1_700_000_000_001,
             model="m", user_id=uid, api_key_id=kid)
    for _ in range(5):
        assert reqs(admin).status_code == 200
        assert admin.get("/admin/api/overview").status_code == 200
        assert admin.get("/admin/api/system").status_code == 200
    from test_admin_usage import summary
    s = summary(admin, period="all").json()["summary"]
    assert s["requests"] == 1                         # 只有那条真实流量


# ---------- §57 全链路：init→login→user→key→chat→429→全部 Admin 视图一致 ----------

def test_full_dashboard_flow(ctx):
    admin, uid, kid, token = ctx
    # rpm=1 Key：第 1 条成功，第 2 条限流 429
    kid2 = admin.post("/admin/api/keys",
                      json={"user_id": uid, "name": "k-rpm", "rpm": 1},
                      headers={"Origin": ORIGIN}).json()
    token2 = kid2["api_key"]
    body = {"model": "test-model",
            "messages": [{"role": "user", "content": "hello"}]}
    h = {"Authorization": f"Bearer {token2}"}
    assert admin.post("/v1/chat/completions", headers=h, json=body).status_code == 200
    assert admin.post("/v1/chat/completions", headers=h, json=body).status_code == 429
    assert wait_log_count(admin.cfg.database.path, 2) >= 2

    s = summary(admin, period="all").json()["summary"]
    assert s["requests"] == 2 and s["success"] == 1 and s["failed"] == 1
    ts = admin.get("/admin/api/usage/timeseries",
                   params={"period": "all", "group_by": "hour"}).json()
    assert sum(i["requests"] for i in ts["items"]) == 2
    ov = admin.get("/admin/api/overview").json()["today"]
    assert ov["requests"] == 2
    assert admin.get("/admin/api/system").json()["database"]["status"] == "healthy"
    errs = reqs(admin, errors_only="true").json()["items"]
    assert [it["error_type"] for it in errs] == ["rate_limited"]
    assert errs[0]["status_code"] == 429
    assert len(reqs(admin).json()["items"]) == 2
