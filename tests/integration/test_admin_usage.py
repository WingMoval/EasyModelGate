"""v0.1.1 Task 4 集成测试：Usage Admin API（summary / timeseries）。

所有时间锚点：today/yesterday/week/month 以“配置时区午夜”为锚（跨午夜确定），
相对窗口（24h/7d）锚定 now；custom 用固定日期。禁止 sleep / 跨午夜歧义 fixture。
"""
from __future__ import annotations

import io
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import VALID_TOKEN  # noqa: F401  (供 emg Bearer 鉴权对照)

from easymodelgate import cli
from easymodelgate.services import usage_service

PW = "synthetic-adm1n-pw-123"
ORIGIN = "http://testserver"
TZ = "Asia/Shanghai"


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


@pytest.fixture()
def ids(admin_client):
    """经 Admin API 建 user + key，返回 (client, user_id, key_id)。"""
    u = admin_client.post("/admin/api/users", json={"username": "alice"},
                          headers={"Origin": ORIGIN}).json()["id"]
    k = admin_client.post("/admin/api/keys",
                          json={"user_id": u, "name": "k1"},
                          headers={"Origin": ORIGIN}).json()["key"]["id"]
    return admin_client, u, k


def seed_log(db_path, *, started_at, model, user_id=1, api_key_id=1,
             status=200, error_type=None, prompt=10, completion=5, total=15,
             cached=2, duration=100, queue=10, upstream=80, ttft=20):
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            """INSERT INTO request_logs
                 (request_id, user_id, api_key_id, backend_id, model, endpoint,
                  started_at, finished_at, duration_ms, queue_wait_ms,
                  upstream_duration_ms, ttft_ms, prompt_tokens,
                  completion_tokens, total_tokens, cached_tokens, stream,
                  finish_reason, status_code, upstream_status_code, error_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"req-{started_at}-{model}", user_id, api_key_id, 1, model,
             "/v1/chat/completions", started_at, started_at + duration,
             duration, queue, upstream, ttft, prompt, completion, total,
             cached, 0, "stop", status, status, error_type))
        con.commit()
    finally:
        con.close()


def _tznow() -> datetime:
    return datetime.now(ZoneInfo(TZ))


def _midnight(dt: datetime | None = None) -> int:
    d = (dt or _tznow()).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp() * 1000)


def summary(admin, **params):
    return admin.get("/admin/api/usage/summary", params=params)


# ---------- 空数据 ----------

def test_empty_summary_zero(admin_client):
    r = summary(admin_client, period="today")
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["requests"] == 0 and s["total_tokens"] == 0
    assert s["success_rate"] == 0.0          # 冻结：0 请求 → 0.0
    assert s["avg_duration_ms"] is None and s["max_queue_wait_ms"] is None
    body = r.json()
    assert body["filters"] == {"user_id": None, "key_id": None, "model": None}
    assert body["range"]["timezone"] == TZ


def test_empty_timeseries(admin_client):
    r = summary(admin_client, period="today")  # noqa: 触发一次无副作用
    r = admin_client.get("/admin/api/usage/timeseries",
                         params={"period": "all", "group_by": "day"})
    assert r.status_code == 200 and r.json()["items"] == []


# ---------- period 语义（全部午夜锚点） ----------

def test_periods(ids):
    admin, uid, kid = ids
    db = admin.cfg.database.path
    now_ms = int(time.time() * 1000)
    mid = _midnight()
    seed_log(db, started_at=mid + 3_600_000, model="m_today",
             user_id=uid, api_key_id=kid)
    seed_log(db, started_at=mid - 3_600_000, model="m_yest",
             user_id=uid, api_key_id=kid)
    seed_log(db, started_at=now_ms - 7_200_000, model="m_24h",
             user_id=uid, api_key_id=kid)
    wk = mid - (_tznow().weekday()) * 86_400_000
    seed_log(db, started_at=wk + 3_600_000, model="m_week",
             user_id=uid, api_key_id=kid)
    mos = _midnight(_tznow().replace(day=1))
    seed_log(db, started_at=mos + 3_600_000, model="m_month",
             user_id=uid, api_key_id=kid)
    expect = {"today": "m_today", "yesterday": "m_yest", "24h": "m_24h",
              "week": "m_week", "month": "m_month"}
    for period, model in expect.items():
        s = summary(admin, period=period, model=model).json()["summary"]
        assert s["requests"] == 1, period
    s = summary(admin, period="all").json()["summary"]
    assert s["requests"] == 5
    # yesterday 与 today 互斥窗口
    assert summary(admin, period="today", model="m_yest").json()["summary"]["requests"] == 0


# ---------- custom ----------

def test_custom_range(ids):
    admin, uid, kid = ids
    db = admin.cfg.database.path
    t0 = int(datetime(2026, 1, 1, 8, 0, tzinfo=ZoneInfo(TZ)).timestamp() * 1000)
    seed_log(db, started_at=t0, model="m_c", user_id=uid, api_key_id=kid)
    r = summary(admin, **{"from": "2026-01-01 00:00", "to": "2026-01-02 00:00"})
    assert r.status_code == 200
    j = r.json()
    assert j["range"]["from_ms"] == int(datetime(2026, 1, 1, tzinfo=ZoneInfo(TZ)).timestamp() * 1000)
    assert j["summary"]["requests"] == 1
    # from == to 与 from > to → 400，且不进 SQL
    for bad in (("2026-01-01 00:00", "2026-01-01 00:00"),
                ("2026-01-02 00:00", "2026-01-01 00:00")):
        b = summary(admin, **{"from": bad[0], "to": bad[1]})
        assert b.status_code == 400 and b.json()["error"]["code"] == "invalid_time_range"
    b = summary(admin, **{"from": "garbage"})
    assert b.status_code == 400 and b.json()["error"]["code"] == "invalid_time_range"
    # custom 优先于 period（与 CLI 冻结一致）
    r = summary(admin, period="today", **{"from": "2026-01-01 00:00",
                                          "to": "2026-01-02 00:00"})
    assert r.json()["summary"]["requests"] == 1


# ---------- 参数校验 ----------

def test_bad_period_and_group_by(admin_client):
    r = summary(admin_client, period="nope")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_period"
    r = admin_client.get("/admin/api/usage/timeseries",
                         params={"group_by": "nope"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_group_by"
    r = summary(admin_client, user_id="abc")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_unknown_filters_404(admin_client):
    r = summary(admin_client, user_id="999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "user_not_found"
    r = summary(admin_client, key_id="999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "key_not_found"


def test_user_key_cross_filter_empty(ids):
    admin, uid, kid = ids
    other = admin.post("/admin/api/users", json={"username": "bob"},
                       headers={"Origin": ORIGIN}).json()["id"]
    r = summary(admin, user_id=other, key_id=kid)
    assert r.status_code == 200
    assert r.json()["summary"]["requests"] == 0     # 交集为空，不报权限错
    assert r.json()["filters"] == {"user_id": other, "key_id": kid, "model": None}


# ---------- 指标与过滤 ----------

def test_metrics_fields(ids):
    admin, uid, kid = ids
    db = admin.cfg.database.path
    mid = _midnight()
    seed_log(db, started_at=mid + 3_600_000, model="mA", user_id=uid,
             api_key_id=kid, prompt=10, completion=5, total=15, cached=2)
    seed_log(db, started_at=mid + 4_000_000, model="mB", user_id=uid,
             api_key_id=kid, status=500, error_type="upstream_error",
             prompt=0, completion=0, total=0, cached=0)
    s = summary(admin, period="all").json()["summary"]
    assert s == {
        "requests": 2, "success": 1, "failed": 1, "success_rate": 0.5,
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
        "cached_tokens": 2, "avg_duration_ms": 100.0,
        "avg_queue_wait_ms": 10.0, "max_queue_wait_ms": 10.0,
        "avg_upstream_ms": 80.0, "avg_ttft_ms": 20.0}
    # 过滤一致性
    assert summary(admin, period="all", user_id=uid).json()["summary"]["requests"] == 2
    assert summary(admin, period="all", key_id=kid).json()["summary"]["requests"] == 2
    assert summary(admin, period="all", model="mA").json()["summary"]["success"] == 1
    assert summary(admin, period="all", model="mB").json()["summary"]["failed"] == 1


# ---------- timeseries ----------

def test_timeseries_groupings(ids):
    admin, uid, kid = ids
    db = admin.cfg.database.path
    mid = _midnight()
    seed_log(db, started_at=mid + 3_600_000, model="mA", user_id=uid,
             api_key_id=kid)
    seed_log(db, started_at=mid - 3_600_000, model="mA", user_id=uid,
             api_key_id=kid)

    def ts(**p):
        r = admin.get("/admin/api/usage/timeseries", params=p)
        assert r.status_code == 200
        return r.json()

    j = ts(period="all", group_by="day", model="mA")
    assert j["group_by"] == "day" and len(j["items"]) == 2
    day_today = _tznow().strftime("%Y-%m-%d")
    day_yest = (_tznow() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert {i["bucket"] for i in j["items"]} == {day_today, day_yest}
    item = j["items"][0]
    assert set(item) == {"bucket", "requests", "success", "failed",
                         "prompt_tokens", "completion_tokens", "total_tokens",
                         "cached_tokens", "avg_duration_ms",
                         "avg_queue_wait_ms", "avg_upstream_ms", "avg_ttft_ms"}
    j = ts(period="all", group_by="hour", model="mA")
    assert len(j["items"]) == 2
    j = ts(period="all", group_by="month", model="mA")
    assert j["items"][-1]["requests"] >= 1
    j = ts(period="all", group_by="week", model="mA")
    assert "W" in j["items"][0]["bucket"]
    # group_by=none → 单桶（analytics 自然行为，冻结为方案 A）
    j = ts(period="all", group_by="none", model="mA")
    assert len(j["items"]) == 1 and j["items"][0]["requests"] == 2
    # 缺省 group_by = period 默认粒度（all → day，与 CLI 一致）
    j = ts(period="all", model="mA")
    assert j["group_by"] == "day" and len(j["items"]) == 2
    # 无 period 无 from/to → 全时段总计，默认 none → 单桶
    j = ts(model="mA")
    assert j["group_by"] == "none" and len(j["items"]) == 1


# ---------- CLI parity（同一 DB 同一过滤器） ----------

def test_cli_admin_usage_parity(ids, capsys):
    admin, uid, kid = ids
    db = admin.cfg.database.path
    mid = _midnight()
    for i in range(3):
        seed_log(db, started_at=mid + 3_600_000 + i, model="mP", user_id=uid,
                 api_key_id=kid, prompt=10, completion=5, total=15, cached=2)
    seed_log(db, started_at=mid + 9_000_000, model="mP", user_id=uid,
             api_key_id=kid, status=429, error_type="rate_limited",
             prompt=0, completion=0, total=0, cached=0)
    rc = cli.main(["--config", admin.cfg_path, "usage", "summary",
                   "--period", "all", "--model", "mP", "--group-by", "none"])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    cells = out[-1].split("  ")
    assert cells[0] == "TOTAL"
    cli_vals = [int(cells[i]) for i in range(1, 8)]
    s = summary(admin, period="all", model="mP").json()["summary"]
    admin_vals = [s["requests"], s["success"], s["failed"],
                  s["prompt_tokens"], s["completion_tokens"],
                  s["total_tokens"], s["cached_tokens"]]
    assert cli_vals == admin_vals == [4, 3, 1, 30, 15, 45, 6]
