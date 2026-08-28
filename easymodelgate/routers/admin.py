"""Admin API 路由组装：认证端点 + 受保护路由组（Web Foundation §13/§16）。

认证边界：
- POST /admin/api/auth/login 是显式未认证例外；
- POST /admin/api/auth/logout 幂等（会话失效也能完成，仅清 cookie）；
- 其余 /admin/api/* 全部挂在 admin_protected_router 上，由
  require_admin_session 统一保护——Task 3+ 的 users/keys/usage 只需
  include 到该子路由，天然继承认证，无需逐端点手工添加。

安全：
- 全部非 GET Admin 请求做 Origin 精确校验（CSRF，SameSite=Lax 双保险）；
  无 Origin 的非 GET 一律拒绝，curl 需显式携带同源 Origin 头；
- 错误信封复用 core/errors，不泄漏密码/哈希/盐/session id；
- 日志绝不包含请求体、密码、session id。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..core.admin_session import (SESSION_COOKIE_NAME, SESSION_TTL_SECONDS,
                                  LoginRateLimiter, Session, SessionStore)
from ..core.errors import ApiError
from ..services import admin_auth_service

logger = logging.getLogger("easymodelgate.admin")


def _session_store(request: Request) -> SessionStore:
    return request.app.state.admin_sessions


def _limiter(request: Request) -> LoginRateLimiter:
    return request.app.state.admin_login_limiter


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _request_origin(request: Request) -> str:
    """推导当前 Admin Origin：反代场景优先 X-Forwarded-Proto（取首值）。"""
    scheme = request.url.scheme
    xfp = request.headers.get("x-forwarded-proto")
    if xfp:
        scheme = xfp.split(",")[0].strip() or scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}"


async def require_same_origin(request: Request) -> None:
    """非 GET Admin 请求的 CSRF/Origin 校验；GET/HEAD/OPTIONS 直接放行。"""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin")
    if not origin:
        raise ApiError(403, "State-changing admin request requires a "
                            "matching Origin header",
                       err_type="invalid_request_error",
                       code="csrf_origin_invalid")
    if origin.rstrip("/") != _request_origin(request).rstrip("/"):
        raise ApiError(403, "Origin does not match the admin endpoint",
                       err_type="invalid_request_error",
                       code="csrf_origin_invalid")


async def require_admin_session(request: Request) -> Session:
    """认证依赖：Task 3+ 的 users/keys/usage Admin API 直接复用。"""
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        raise ApiError(401, "Admin authentication required",
                       err_type="authentication_error",
                       code="admin_auth_required")
    state, session = _session_store(request).lookup(sid)
    if state == "expired":
        raise ApiError(401, "Admin session has expired",
                       err_type="authentication_error",
                       code="admin_session_expired")
    if session is None:
        raise ApiError(401, "Admin authentication required",
                       err_type="authentication_error",
                       code="admin_auth_required")
    return session


# 受保护组工厂：组级依赖 = 会话认证 + CSRF Origin 校验（后者对 GET 自动放行）。
# 每次 create_app 新建实例（避免多次装配时路由在共享 router 上累积）；
# 业务路由 include 进组即自动继承认证，无需逐端点手工添加。
def make_protected_router() -> APIRouter:
    return APIRouter(
        dependencies=[Depends(require_admin_session),
                      Depends(require_same_origin)])


def _cookie_kwargs(secure: bool) -> dict:
    return dict(path="/admin", httponly=True, samesite="lax",
                secure=secure, max_age=SESSION_TTL_SECONDS)


def _is_https(request: Request) -> bool:
    return _request_origin(request).startswith("https://")


async def _parse_password(request: Request) -> str:
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "Request body must be JSON",
                       err_type="invalid_request_error", code="bad_request")
    if not isinstance(body, dict) or not isinstance(body.get("password"), str):
        raise ApiError(422, "Field 'password' (string) is required",
                       err_type="invalid_request_error",
                       code="validation_error", param="password")
    return body["password"]


def build_admin_api_router() -> APIRouter:
    router = APIRouter()
    protected = make_protected_router()
    login_router = APIRouter(prefix="/admin/api/auth")

    @login_router.post("/login")
    async def admin_login(request: Request) -> JSONResponse:
        await require_same_origin(request)
        limiter = _limiter(request)
        key = _client_key(request)
        if limiter.blocked(key):
            raise ApiError(429, "Too many failed login attempts",
                           err_type="rate_limit_error",
                           code="admin_login_rate_limited")
        password = await _parse_password(request)
        db = request.app.state.db
        if not await admin_auth_service.is_admin_initialized(db):
            # fail-closed：绝不自动创建默认管理员
            raise ApiError(503, "Admin is not initialized; run "
                                "'easymodelgate admin init' first",
                           err_type="api_error", code="admin_not_initialized")
        ok = await admin_auth_service.verify_admin_password(db, password)
        if not ok:
            limiter.record_failure(key)
            logger.warning("admin login failed from %s", key)  # 不记录 body/密码
            raise ApiError(401, "Invalid credentials",
                           err_type="authentication_error",
                           code="invalid_admin_credentials")
        limiter.reset(key)
        session = _session_store(request).create()
        resp = JSONResponse(status_code=200, content={"authenticated": True})
        resp.set_cookie(SESSION_COOKIE_NAME, session.session_id,
                        **_cookie_kwargs(_is_https(request)))
        return resp

    @login_router.post("/logout")
    async def admin_logout(request: Request) -> JSONResponse:
        await require_same_origin(request)
        sid = request.cookies.get(SESSION_COOKIE_NAME)
        if sid:
            _session_store(request).delete(sid)
        resp = JSONResponse(status_code=200, content={"authenticated": False})
        cookie = _cookie_kwargs(_is_https(request))
        cookie["max_age"] = 0
        resp.set_cookie(SESSION_COOKIE_NAME, "", **cookie)  # 幂等清除
        return resp

    @protected.get("/admin/api/auth/me")
    async def admin_me(session: Session = Depends(require_admin_session)) -> dict:
        return {"authenticated": True}

    # 业务路由：include 进 protected 即继承 require_admin_session + CSRF
    from .admin_keys import router as keys_router
    from .admin_users import router as users_router
    protected.include_router(users_router)
    protected.include_router(keys_router)

    router.include_router(login_router)
    router.include_router(protected)
    return router
