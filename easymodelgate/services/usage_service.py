"""用量查询共享业务服务（CLI 与未来 Admin API 共用）。

职责：period / custom from-to 解析、group_by 归一化、过滤条件解析，
最终调用 analytics.summary()——聚合算法唯一真相，本模块不做任何统计 SQL。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..db.database import Database
from . import analytics, key_service, user_service

PERIOD_DEFAULT_GROUP = {
    "today": "hour", "yesterday": "hour", "24h": "hour",
    "7d": "day", "week": "day", "month": "day", "all": "day",
}


def parse_local_ms(s: str | None, tz_name: str) -> int | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return int(dt.timestamp() * 1000)


def resolve_time_range(period: str | None, from_str: str | None,
                       to_str: str | None, tz_name: str, *,
                       now: datetime | None = None
                       ) -> tuple[int | None, int | None, str]:
    """返回 (start_ms, end_ms, default_group_by)。语义与 v0.1 CLI 一致：

    - custom（--from/--to）优先，默认 group_by=day；
    - period：today/yesterday 等按配置时区解释，默认 group_by 见
      PERIOD_DEFAULT_GROUP；all → 不限时间；
    - 两者皆无 → 全时段总计（group_by=none）。
    """
    if from_str or to_str:
        start_ms = parse_local_ms(from_str, tz_name)
        end_ms = parse_local_ms(to_str, tz_name)
        return start_ms, end_ms, "day"
    if period:
        now = now or datetime.now(ZoneInfo(tz_name))
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ms = end_ms = None
        if period == "today":
            start_ms = int(midnight.timestamp() * 1000)
        elif period == "yesterday":
            y = midnight - timedelta(days=1)
            start_ms = int(y.timestamp() * 1000)
            end_ms = start_ms + 86_400_000
        elif period == "24h":
            start_ms = int((now - timedelta(hours=24)).timestamp() * 1000)
        elif period == "7d":
            start_ms = int((now - timedelta(days=7)).timestamp() * 1000)
        elif period == "week":
            week_start = midnight - timedelta(days=now.weekday())
            start_ms = int(week_start.timestamp() * 1000)
        elif period == "month":
            month_start = now.replace(day=1, hour=0, minute=0,
                                      second=0, microsecond=0)
            start_ms = int(month_start.timestamp() * 1000)
        elif period == "all":
            pass
        else:
            raise ValueError(f"未知 period {period}")
        return start_ms, end_ms, PERIOD_DEFAULT_GROUP.get(period, "day")
    return None, None, "none"


async def resolve_filters(db: Database, *, username: str | None = None,
                          key_prefix: str | None = None
                          ) -> tuple[int | None, int | None]:
    """username → user_id；key prefix → api_key_id。

    可能抛出 user_service.UserNotFound / key_service.AmbiguousKeyPrefix。
    """
    user_id = None
    if username:
        user_id = int((await user_service.require_user(db, username))["id"])
    api_key_id = None
    if key_prefix:
        api_key_id = int((await key_service.resolve_key_prefix(db, key_prefix))["id"])
    return user_id, api_key_id


async def summarize(db: Database, f: analytics.SummaryFilter) -> list[dict]:
    return await analytics.summary(db, f)
