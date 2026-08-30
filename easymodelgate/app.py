"""FastAPI 应用组装与生命周期管理。"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time as _t

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from . import __version__
from .config import AppConfig, load_config
from .core.concurrency import UpstreamSlots
from .core.errors import register_error_handlers
from .core.ratelimit import FixedWindowRpmLimiter
from .db.database import Database
from .proxy.upstream import UpstreamClient
from .core.admin_session import LoginRateLimiter, SessionStore
from .routers.admin import build_admin_api_router
from .routers.admin_web import build_admin_web_router, mount_static_files
from .routers.public import router as public_router

logger = logging.getLogger("easymodelgate.app")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    
    # CSP for Admin HTML pages - strict, no unsafe-inline
    CSP_ADMIN = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    
    # CSP for Public API - minimal
    CSP_API = (
        "default-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "form-action 'none'"
    )
    
    # CSP for Static files - self only
    CSP_STATIC = (
        "default-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Add security headers to all responses
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        # Apply CSP based on path
        path = request.url.path
        if path.startswith("/admin"):
            if path.startswith("/admin/static"):
                response.headers["Content-Security-Policy"] = self.CSP_STATIC
            else:
                response.headers["Content-Security-Policy"] = self.CSP_ADMIN
        elif path.startswith("/v1"):
            response.headers["Content-Security-Policy"] = self.CSP_API
        elif path.startswith("/health"):
            response.headers["Content-Security-Policy"] = self.CSP_API
        
        return response


_BACKEND_SEED_SQL = (
    "INSERT OR IGNORE INTO backends (name, type, base_url, api_key_ref, enabled, created_at) "
    "VALUES ('local-llamacpp', 'llamacpp', ?, ?, 1, ?)"
)


async def _seed_backend(db: Database, cfg: AppConfig) -> None:
    """backends 为空时按配置写入种子行（见 ADR-0003）。

    api_key_ref 只记录密钥来源描述（文件路径或环境变量名），不存密钥本体。
    """
    key_ref = ("env:EMG_UPSTREAM_API_KEY"
               if os.environ.get("EMG_UPSTREAM_API_KEY")
               else f"file:{cfg.upstream.api_key_file}")
    import time as _time
    await db.conn.execute(
        _BACKEND_SEED_SQL,
        (cfg.upstream.base_url, key_ref, int(_time.time() * 1000)))
    await db.conn.commit()


def create_app(cfg: AppConfig | None = None) -> FastAPI:
    cfg = cfg or load_config()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        db = await Database(cfg.database.path).connect()
        await _seed_backend(db, cfg)
        cur = await db.conn.execute(
            "SELECT id FROM backends WHERE name='local-llamacpp' AND enabled=1")
        row = await cur.fetchone()
        app.state.cfg = cfg
        app.state.db = db
        app.state.backend_id = int(row["id"]) if row else None
        app.state.started_monotonic = _t.monotonic()
        app.state.started_at_ms = int(_t.time() * 1000)
        app.state.background_tasks: set[asyncio.Task] = set()
        app.state.upstream = UpstreamClient(cfg)
        app.state.slots = UpstreamSlots(cfg.upstream.slots)
        app.state.limiter = FixedWindowRpmLimiter()
        logger.info(
            "EasyModelGate %s 启动 db=%s upstream=%s slots=%d",
            __version__, cfg.database.path, cfg.upstream.base_url, cfg.upstream.slots)
        try:
            yield
        finally:
            await app.state.upstream.aclose()
            pending = [t for t in app.state.background_tasks if not t.done()]
            if pending:
                # 规格 §36：shutdown 给日志类后台任务合理 flush 时间
                await asyncio.wait(pending, timeout=5.0)
            await db.close()
            logger.info("EasyModelGate 已停止")

    app = FastAPI(
        title="EasyModelGate",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    register_error_handlers(app)
    app.include_router(public_router)
    # Admin 会话与登录限速：进程内状态（重启需重登，v0.1.1 MVP 冻结边界）
    app.state.admin_sessions = SessionStore()
    app.state.admin_login_limiter = LoginRateLimiter()
    app.include_router(build_admin_api_router())
    app.include_router(build_admin_web_router())
    mount_static_files(app)

    def spawn(coro) -> asyncio.Task:
        """创建受管理的 detached task（防 GC、shutdown 可等待，规格 §36）。"""
        task = asyncio.get_running_loop().create_task(coro)
        bg: set[asyncio.Task] = app.state.background_tasks
        bg.add(task)
        task.add_done_callback(bg.discard)
        return task

    app.state.spawn = spawn
    return app
