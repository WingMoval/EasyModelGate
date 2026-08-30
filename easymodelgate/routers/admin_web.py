"""Admin Web UI routes (HTML pages) — Jinja2 templates, login, layout, static files."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import jinja2
from starlette.templating import Jinja2Templates

from ..core.admin_session import SessionStore

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


class NoCacheTemplates(Jinja2Templates):
    """Jinja2Templates with cache disabled to avoid jinja2 3.x cache key bug."""
    def __init__(self, directory: str | Path):
        self.context_processors = []
        loader = jinja2.FileSystemLoader(str(directory))
        self.env = jinja2.Environment(
            loader=loader,
            autoescape=jinja2.select_autoescape(),
            cache_size=0,
        )
        self._setup_env_defaults(self.env)


templates = NoCacheTemplates(str(TEMPLATES_DIR))

router = APIRouter(tags=["admin-web"])

LOGIN_PATH = "/admin/login"


async def check_admin_session(request: Request) -> bool:
    """Check if admin session is valid."""
    session_id = request.cookies.get("emg_admin_session")
    if not session_id:
        return False
    session_store: SessionStore = request.app.state.admin_sessions
    status, _ = session_store.lookup(session_id)
    return status == "valid"


def redirect_to_login(request: Request) -> RedirectResponse:
    """Create a redirect response to login page."""
    return RedirectResponse(
        url=f"/admin/login?redirect={request.url.path}",
        status_code=status.HTTP_303_SEE_OTHER
    )


# ---- Login page ----
@router.get(LOGIN_PATH, response_class=HTMLResponse, name="admin_login")
async def login_page(request: Request):
    # If already logged in, redirect to dashboard
    if await check_admin_session(request):
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    # Check if admin is initialized
    db = request.app.state.db
    cur = await db.conn.execute("SELECT value_json FROM settings WHERE key = 'admin.auth'")
    row = await cur.fetchone()
    initialized = row is not None and row[0] is not None

    return templates.TemplateResponse(request, "login.html", {
        "initialized": initialized,
        "active_nav": "login",
        "page_title": "Login"
    })


# ---- Protected HTML pages ----
@router.get("/admin", response_class=HTMLResponse, name="admin_overview")
async def overview_page(request: Request):
    if not await check_admin_session(request):
        return redirect_to_login(request)
    return templates.TemplateResponse(request, "overview.html", {
        "active_nav": "overview",
        "page_title": "Overview"
    })


@router.get("/admin/users", response_class=HTMLResponse, name="admin_users")
async def users_page(request: Request):
    if not await check_admin_session(request):
        return redirect_to_login(request)
    return templates.TemplateResponse(request, "users.html", {
        "active_nav": "users",
        "page_title": "Users"
    })


@router.get("/admin/keys", response_class=HTMLResponse, name="admin_keys")
async def keys_page(request: Request):
    if not await check_admin_session(request):
        return redirect_to_login(request)
    return templates.TemplateResponse(request, "keys.html", {
        "active_nav": "keys",
        "page_title": "API Keys"
    })


@router.get("/admin/usage", response_class=HTMLResponse, name="admin_usage")
async def usage_page(request: Request):
    if not await check_admin_session(request):
        return redirect_to_login(request)
    return templates.TemplateResponse(request, "usage.html", {
        "active_nav": "usage",
        "page_title": "Usage"
    })


@router.get("/admin/system", response_class=HTMLResponse, name="admin_system")
async def system_page(request: Request):
    if not await check_admin_session(request):
        return redirect_to_login(request)
    return templates.TemplateResponse(request, "system.html", {
        "active_nav": "system",
        "page_title": "System"
    })


# ---- Logout (POST to match API) ----
@router.post("/admin/logout", name="admin_logout")
async def logout_page(request: Request):
    session_id = request.cookies.get("emg_admin_session")
    if session_id:
        session_store: SessionStore | None = getattr(request.app.state, "admin_sessions", None)
        if session_store is not None:
            session_store.delete(session_id)

    response = RedirectResponse(url=LOGIN_PATH, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("emg_admin_session", path="/admin", httponly=True, samesite="lax")
    return response


def build_admin_web_router() -> APIRouter:
    """Build the admin web router with all HTML routes."""
    return router


def mount_static_files(app) -> None:
    """Mount static files for admin web UI."""
    app.mount("/admin/static", StaticFiles(directory=str(STATIC_DIR)), name="admin-static")
