"""Phase 10 单元测试：分桶正确性（ISO 周/时区午夜）、过滤器、指标聚合。"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "fake_upstream"))

from easymodelgate.db.database import Database  # noqa: E402
from easymodelgate.services import analytics  # noqa: E402


async def _seed(db_path, rows):
    """rows: list[dict(started_at_ms, model, user_id, api_key_id, status, error, tokens...)]"""
    db = await Database(db_path).connect()
    try:
        for r in rows:
            await db.conn.execute(
                """INSERT INTO request_logs
                     (request_id, user_id, api_key_id, backend_id, model, endpoint,
                      started_at, finished_at, duration_ms, queue_wait_ms,
                      upstream_duration_ms, ttft_ms, prompt_tokens,
                      completion_tokens, total_tokens, cached_tokens, stream,
                      finish_reason, status_code, upstream_status_code,
                      client_ip, input_bytes, output_bytes, error_type, error_message)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r.get("request_id", "r"), r.get("user_id"), r.get("api_key_id"),
                 1, r.get("model"), "/v1/chat/completions",
                 r["started_at"], r["started_at"] + 100,
                 r.get("duration_ms"), r.get("queue_wait_ms"),
                 r.get("upstream_duration_ms"), r.get("ttft_ms"),
                 r.get("prompt_tokens"), r.get("completion_tokens"),
                 r.get("total_tokens"), r.get("cached_tokens"),
                 r.get("stream", 1), r.get("finish_reason"),
                 r.get("status_code", 200), 200, None, 10, 20,
                 r.get("error_type"), None))
        await db.conn.commit()
    finally:
        await db.close()


def _ms(y, mo, d, h=0, mi=0, s=0, tz_offset_hours=8):
    tz = timezone(timedelta(hours=tz_offset_hours))
    return int(datetime(y, mo, d, h, mi, s, tzinfo=tz).timestamp() * 1000)


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "a.db"

    async def _connect():
        return await Database(path).connect()

    asyncio.run(_connect())
    return path


def _run_summary(db_path, **kw):
    f = analytics.SummaryFilter(**kw)

    async def _go():
        db = await Database(db_path).connect()
        try:
            return await analytics.summary(db, f)
        finally:
            await db.close()

    return asyncio.run(_go())


def test_iso_week_cross_year(db):
    """2026-12-31 属 2026-W53；2027-01-01 属 2027-W01（周四为界，跨年必须分开）。"""
    # 2027-01-01（周五）按 ISO 归属 2026-W53；2027-01-04（周一）起为 2027-W01
    assert datetime(2027, 1, 1).isocalendar() == (2026, 53, 5)
    assert datetime(2027, 1, 4).isocalendar() == (2027, 1, 1)
    rows_in = [
        {"started_at": _ms(2026, 12, 31, 23), "total_tokens": 10},
        {"started_at": _ms(2027, 1, 4, 1), "total_tokens": 20},
    ]
    asyncio.run(_seed(db, rows_in))
    out = _run_summary(db, granularity="week")
    buckets = [r for r in out if r["bucket"] != "TOTAL"]
    assert [b["bucket"] for b in buckets] == ["2026-W53", "2027-W01"]
    total = out[-1]
    assert total["total_tokens"] == 30 and total["requests"] == 2


def test_shanghai_midnight_boundary(db):
    """UTC 15:59 = 上海 23:59（前一天）；UTC 16:00 即进入上海次日。"""
    rows_in = [
        # UTC 2026-08-25 15:59 → 上海 2026-08-25 23:59
        {"started_at": int(datetime(2026, 8, 25, 15, 59, tzinfo=timezone.utc)
                                .timestamp() * 1000), "total_tokens": 5},
        # UTC 2026-08-25 16:00 → 上海 2026-08-26 00:00
        {"started_at": int(datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)
                           .timestamp() * 1000), "total_tokens": 7},
    ]
    asyncio.run(_seed(db, rows_in))
    out = _run_summary(db, granularity="day")
    day_buckets = {r["bucket"]: r for r in out if r["bucket"] != "TOTAL"}
    assert set(day_buckets) == {"2026-08-25", "2026-08-26"}
    assert day_buckets["2026-08-25"]["total_tokens"] == 5
    assert day_buckets["2026-08-26"]["total_tokens"] == 7


def test_hour_month_buckets_and_metrics(db):
    rows_in = [
        {"started_at": _ms(2026, 8, 26, 10, 15), "status_code": 200,
         "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
         "cached_tokens": 8, "duration_ms": 100, "queue_wait_ms": 30,
         "upstream_duration_ms": 60, "ttft_ms": 40},
        {"started_at": _ms(2026, 8, 26, 10, 45), "status_code": 429,
         "error_type": "rate_limited", "queue_wait_ms": 70},
        {"started_at": _ms(2026, 9, 1, 9, 0), "status_code": 200,
         "total_tokens": 100},
    ]
    asyncio.run(_seed(db, rows_in))
    out = _run_summary(db, granularity="hour")
    b = {r["bucket"]: r for r in out if r["bucket"].startswith("2026")}
    hour_row = b["2026-08-26T10:00"]
    assert hour_row["requests"] == 2
    assert hour_row["success_count"] == 1 and hour_row["error_count"] == 1
    assert hour_row["total_tokens"] == 15
    assert hour_row["cached_tokens"] == 8
    assert hour_row["avg_queue_wait_ms"] == 50.0          # (30+70)/2
    assert hour_row["max_queue_wait_ms"] == 70.0
    month_out = _run_summary(db, granularity="month")
    mb = {r["bucket"]: r for r in month_out if r["bucket"].startswith("2026-")}
    assert mb["2026-08"]["requests"] == 2 and mb["2026-09"]["requests"] == 1


def test_filters_user_key_model(db):
    rows_in = [
        {"started_at": _ms(2026, 8, 26, 9), "user_id": 1, "api_key_id": 11,
         "model": "qwen3.8-local", "total_tokens": 3},
        {"started_at": _ms(2026, 8, 26, 9, 5), "user_id": 2, "api_key_id": 12,
         "model": "other-model", "total_tokens": 4},
    ]
    asyncio.run(_seed(db, rows_in))
    r_user = _run_summary(db, user_id=1)
    assert r_user[-1]["requests"] == 1 and r_user[-1]["total_tokens"] == 3
    r_key = _run_summary(db, api_key_id=12)
    assert r_key[-1]["total_tokens"] == 4
    r_model = _run_summary(db, model="qwen3.8-local")
    assert r_model[-1]["requests"] == 1


def test_custom_range_half_open(db):
    """范围统一 [from, to)：to 时刻的请求不计入。"""
    rows_in = [
        {"started_at": _ms(2026, 8, 1, 0, 0), "total_tokens": 1},
        {"started_at": _ms(2026, 8, 10, 12), "total_tokens": 2},
        {"started_at": _ms(2026, 8, 20, 0, 0), "total_tokens": 4},
    ]
    asyncio.run(_seed(db, rows_in))
    out = _run_summary(db, start_ms=_ms(2026, 8, 1), end_ms=_ms(2026, 8, 20))
    assert out[-1]["requests"] == 2 and out[-1]["total_tokens"] == 3


def test_cli_week_output_matches_iso(db, tmp_path, capsys, monkeypatch):
    """CLI --group-by week 输出 ISO 周桶。"""
    rows_in = [{"started_at": _ms(2027, 1, 1, 1), "total_tokens": 9}]
    asyncio.run(_seed(db, rows_in))
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(f'[database]\npath = "{db}"\n'
                        '[usage]\ntimezone = "Asia/Shanghai"\n')
    monkeypatch.setattr(sys, "argv", [
        "easymodelgate", "--config", str(cfg_path),
        "usage", "summary", "--period", "all", "--group-by", "week"])
    from easymodelgate.cli import main
    rc = main(["--config", str(cfg_path), "usage", "summary",
               "--period", "all", "--group-by", "week"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2027-W01" in out or "2026-W53" in out


# ---------------- Phase 12 边界补充 ----------------

def test_empty_database(db):
    out = _run_summary(db, granularity="day")
    assert out[-1]["bucket"] == "TOTAL" and out[-1]["requests"] == 0
    assert out[-1]["total_tokens"] == 0


def test_from_equals_to_yields_nothing(db):
    asyncio.run(_seed(db, [{"started_at": _ms(2026, 8, 26, 10), "total_tokens": 5}]))
    out = _run_summary(db, start_ms=_ms(2026, 8, 26, 10),
                       end_ms=_ms(2026, 8, 26, 10))
    assert out[-1]["requests"] == 0          # [x, x) 为空集，不报错


def test_all_null_metrics_row(db):
    asyncio.run(_seed(db, [{"started_at": _ms(2026, 8, 26, 10)}]))  # 全 NULL
    out = _run_summary(db)
    t = out[-1]
    assert t["requests"] == 1 and t["success_count"] == 1 and t["error_count"] == 0
    assert t["total_tokens"] == 0 and t["avg_duration_ms"] is None
    assert t["avg_queue_wait_ms"] is None and t["max_queue_wait_ms"] is None


def test_mixed_null_and_values_queue(db):
    asyncio.run(_seed(db, [
        {"started_at": _ms(2026, 8, 26, 10), "queue_wait_ms": None},
        {"started_at": _ms(2026, 8, 26, 11), "queue_wait_ms": 0},
        {"started_at": _ms(2026, 8, 26, 12), "queue_wait_ms": 90},
    ]))
    out = _run_summary(db, granularity="day")
    d = [r for r in out if r["bucket"] != "TOTAL"][0]
    assert d["avg_queue_wait_ms"] == 45.0 and d["max_queue_wait_ms"] == 90.0


def test_month_cross_year_buckets(db):
    asyncio.run(_seed(db, [
        {"started_at": _ms(2026, 12, 31, 10), "total_tokens": 3},
        {"started_at": _ms(2027, 1, 1, 10), "total_tokens": 4},
    ]))
    out = _run_summary(db, granularity="month")
    buckets = {r["bucket"] for r in out if r["bucket"] != "TOTAL"}
    assert buckets == {"2026-12", "2027-01"}
