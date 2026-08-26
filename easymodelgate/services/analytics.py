"""时段用量统计（规格 §43-§45 / Checkpoint 3 §三）。

实现说明：
- v0.1 直接对 request_logs 过滤后取回聚合所需列，在 Python 侧分桶求和。
  数据规模（<100 万行）下性能足够；换取两个正确性收益：
  1) week 分桶使用 datetime.isocalendar()，ISO 年+周跨年正确（替代 SQLite %W）；
  2) 时区转换完全在 Python zoneinfo 完成，SQL 内无任何硬编码偏移。
- 时间范围统一 [from, to)，输入按配置时区解释后转 UTC ms。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

_METRIC_COLUMNS = (
    "status_code", "error_type", "prompt_tokens", "completion_tokens",
    "total_tokens", "cached_tokens",
    "duration_ms", "queue_wait_ms", "upstream_duration_ms", "ttft_ms",
)


def tz_offset_seconds(tz_name: str) -> int:
    offset = ZoneInfo(tz_name).utcoffset(datetime.now())
    return int(offset.total_seconds()) if offset else 0


@dataclass(frozen=True)
class SummaryFilter:
    start_ms: int | None = None
    end_ms: int | None = None          # [start, end)
    user_id: int | None = None
    api_key_id: int | None = None
    model: str | None = None
    granularity: str | None = None     # hour/day/week/month；None 仅总计
    timezone: str = "Asia/Shanghai"


def _bucket_key(ts_ms: int, granularity: str, tz: ZoneInfo) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz)
    if granularity == "hour":
        return dt.strftime("%Y-%m-%dT%H:00")
    if granularity == "day":
        return dt.strftime("%Y-%m-%d")
    if granularity == "month":
        return dt.strftime("%Y-%m")
    if granularity == "week":
        iso = dt.isocalendar()  # ISO 年 + 周：跨年正确
        return f"{iso.year}-W{iso.week:02d}"
    raise ValueError(f"未知粒度 {granularity}")  # pragma: no cover


def _new_bucket() -> dict:
    return {"requests": 0, "success_count": 0, "error_count": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "cached_tokens": 0,
            "_dur": [], "_queue": [], "_upstream": [], "_ttft": []}


def _accumulate(b: dict, row: sqlite3.Row) -> None:
    b["requests"] += 1
    status = row["status_code"]
    if row["error_type"] is None and status is not None and 200 <= status < 400:
        b["success_count"] += 1
    else:
        b["error_count"] += 1
    for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
        v = row[k]
        if isinstance(v, int):
            b[k] += v
    for src, dst in (("duration_ms", "_dur"), ("queue_wait_ms", "_queue"),
                     ("upstream_duration_ms", "_upstream"), ("ttft_ms", "_ttft")):
        v = row[src]
        if isinstance(v, (int, float)):
            b[dst].append(v)


def _finalize(b: dict) -> dict:
    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    return {
        "requests": b["requests"],
        "success_count": b["success_count"],
        "error_count": b["error_count"],
        "prompt_tokens": b["prompt_tokens"],
        "completion_tokens": b["completion_tokens"],
        "total_tokens": b["total_tokens"],
        "cached_tokens": b["cached_tokens"],
        "avg_duration_ms": avg(b["_dur"]),
        "avg_queue_wait_ms": avg(b["_queue"]),
        "max_queue_wait_ms": round(max(b["_queue"]), 1) if b["_queue"] else None,
        "avg_upstream_duration_ms": avg(b["_upstream"]),
        "avg_ttft_ms": avg(b["_ttft"]),
    }


async def summary(db, f: SummaryFilter) -> list[dict]:
    """返回分桶行（有序）+ 末尾 TOTAL 行。"""
    where: list[str] = ["1=1"]
    params: list = []
    if f.start_ms is not None:
        where.append("started_at >= ?")
        params.append(f.start_ms)
    if f.end_ms is not None:
        where.append("started_at < ?")
        params.append(f.end_ms)
    if f.user_id is not None:
        where.append("user_id = ?")
        params.append(f.user_id)
    if f.api_key_id is not None:
        where.append("api_key_id = ?")
        params.append(f.api_key_id)
    if f.model is not None:
        where.append("model = ?")
        params.append(f.model)

    cols = ", ".join(("started_at",) + _METRIC_COLUMNS)
    sql = f"SELECT {cols} FROM request_logs WHERE {' AND '.join(where)}"
    cur = await db.conn.execute(sql, params)
    rows = await cur.fetchall()

    tz = ZoneInfo(f.timezone)
    buckets: dict[str, dict] = {}
    total = _new_bucket()
    for row in rows:
        _accumulate(total, row)
        if f.granularity is not None:
            key = _bucket_key(row["started_at"], f.granularity, tz)
            _accumulate(buckets.setdefault(key, _new_bucket()), row)

    out = [{"bucket": k, **_finalize(v)} for k, v in sorted(buckets.items())]
    out.append({"bucket": "TOTAL", **_finalize(total)})
    return out
