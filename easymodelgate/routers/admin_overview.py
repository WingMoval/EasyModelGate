"""Overview + System Admin API（Dashboard 首页 / 系统状态卡片）。

- gateway：进程内静态 healthy（不自调 HTTP）；
- backend：复用 app 的 upstream client 真实轻量探测，失败降级 unhealthy；
- today：复用 usage_service/analytics（零第二套 SQL）；
- database：SELECT 1；不泄漏路径；不 VACUUM/PRAGMA 写入；
- 零服务器控制（无 GPU/CPU/内存/systemd/进程信息）。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request

from .. import __version__
from ..db import dao
from ..services import usage_service
from .admin_common import backend_status, database_status, metrics_body
from .admin_usage import _usage_rows

router = APIRouter(prefix="/admin")


async def _today_metrics(request: Request) -> dict:
    """today 指标：与 /usage/summary?period=today 完全同一代码路径。"""
    tz = request.app.state.cfg.usage.timezone
    start_ms, end_ms, _gb = usage_service.resolve_time_range(
        "today", None, None, tz)
    rows = await _usage_rows(request, start_ms, end_ms, tz, None, None, None,
                             None)
    return metrics_body(rows[-1], with_max_queue=True)


@router.get("/api/overview")
async def overview(request: Request) -> dict:
    db = request.app.state.db
    today = await _today_metrics(request)
    return {
        "gateway": {"status": "healthy"},
        "backend": {"status": await backend_status(request.app)},
        "today": today,
        "active_keys": await dao.count_enabled_keys(db),
    }


@router.get("/api/system")
async def system(request: Request) -> dict:
    app = request.app
    now = time.monotonic()
    return {
        "version": __version__,
        "gateway": {"status": "healthy"},
        "backend": {"status": await backend_status(app)},
        "database": {"status": await database_status(app)},
        "uptime_seconds": round(now - app.state.started_monotonic, 1),
        "started_at": app.state.started_at_ms,
    }
