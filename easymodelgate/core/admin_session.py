"""进程内 Admin 会话存储与登录限速（Web Foundation §10/§17-R3 冻结边界）。

- 会话仅存于进程内存：网关重启全员掉线重登，属 v0.1.1 MVP 预期行为；
  不引入 Redis / 新表 / 外部 session 服务。
- cookie 只携带随机 session id；派生密钥等凭据绝不进入 cookie。
- 绝对过期 12h，懒清理，无后台线程；时钟可注入（now_fn）便于测试。
- 登录限速按来源 IP 计数，成功登录清零；同样可注入时钟。
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

SESSION_COOKIE_NAME = "emg_admin_session"
SESSION_TTL_SECONDS = 12 * 3600
SESSION_ID_BYTES = 32

LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 300


def new_session_id() -> str:
    return secrets.token_urlsafe(SESSION_ID_BYTES)


@dataclass
class Session:
    session_id: str
    created_at: float
    expires_at: float
    last_seen: float = field(default=0.0)

    def expired(self, now: float) -> bool:
        return now >= self.expires_at


class SessionStore:
    """dict[str, Session] + threading.Lock（uvicorn 单事件循环内亦防多线程误用）。"""

    def __init__(self, *, ttl_seconds: int = SESSION_TTL_SECONDS,
                 now_fn=time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._now = now_fn
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> Session:
        now = self._now()
        sid = new_session_id()
        s = Session(session_id=sid, created_at=now, expires_at=now + self._ttl)
        with self._lock:
            self._sessions[sid] = s
        return s

    def get(self, session_id: str) -> Session | None:
        """返回有效会话；过期即删除并返回 None（懒清理）。"""
        state, session = self.lookup(session_id)
        return session if state == "valid" else None

    def lookup(self, session_id: str) -> tuple[str, Session | None]:
        """区分认证失败原因："valid" / "expired"（曾有效已过期） / "missing"。"""
        now = self._now()
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return "missing", None
            if s.expired(now):
                del self._sessions[session_id]
                return "expired", None
            s.last_seen = now
            return "valid", s

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


class LoginRateLimiter:
    """每来源：窗口内失败次数超限即拒绝；成功登录清除该来源计数。"""

    def __init__(self, *, max_failures: int = LOGIN_MAX_FAILURES,
                 window_seconds: int = LOGIN_WINDOW_SECONDS,
                 now_fn=time.monotonic) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._now = now_fn
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, origin_key: str) -> bool:
        cutoff = self._now() - self._window
        with self._lock:
            ts = [t for t in self._failures.get(origin_key, []) if t > cutoff]
            if ts:
                self._failures[origin_key] = ts
            else:
                self._failures.pop(origin_key, None)
            return len(ts) >= self._max

    def record_failure(self, origin_key: str) -> None:
        cutoff = self._now() - self._window
        with self._lock:
            ts = [t for t in self._failures.get(origin_key, []) if t > cutoff]
            ts.append(self._now())
            self._failures[origin_key] = ts

    def reset(self, origin_key: str) -> None:
        with self._lock:
            self._failures.pop(origin_key, None)
