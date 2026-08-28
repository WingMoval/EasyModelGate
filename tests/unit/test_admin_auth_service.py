"""v0.1.1 Task 2 单元测试：admin 凭据服务 / 会话存储 / 登录限速。

全临时 SQLite；密码为 synthetic 值；时间全部注入 fake clock，无真实等待。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from easymodelgate.core.admin_session import (LoginRateLimiter, SessionStore)
from easymodelgate.db.database import Database
from easymodelgate.services import admin_auth_service as svc

PW = "synthetic-adm1n-pw-123"


@pytest.fixture()
async def db(tmp_path):
    d = await Database(tmp_path / "adm.db").connect()
    try:
        yield d
    finally:
        await d.close()


# ---------- 凭据 ----------

async def test_uninitialized(db):
    assert await svc.is_admin_initialized(db) is False
    assert await svc.get_admin_auth(db) is None


async def test_init_and_verify(db):
    await svc.initialize_admin(db, PW)
    assert await svc.is_admin_initialized(db) is True
    assert await svc.verify_admin_password(db, PW) is True
    assert await svc.verify_admin_password(db, PW + "x") is False


async def test_duplicate_init_rejected(db):
    await svc.initialize_admin(db, PW)
    with pytest.raises(svc.AdminAlreadyInitialized):
        await svc.initialize_admin(db, "other-password")
    assert await svc.verify_admin_password(db, PW)   # 原密码仍有效


async def test_empty_password_rejected(db):
    with pytest.raises(ValueError):
        await svc.initialize_admin(db, "")


async def test_stored_value_is_not_plaintext(db):
    await svc.initialize_admin(db, PW)
    raw = sqlite3.connect(str(db.path)).execute(
        "SELECT value_json FROM settings WHERE key='admin.auth'").fetchone()[0]
    meta = json.loads(raw)
    assert PW not in raw
    assert meta["algorithm"] == "scrypt"
    assert meta["n"] == 2 ** 15 and meta["r"] == 8 and meta["p"] == 1
    assert len(bytes.fromhex(meta["salt"])) == 16
    assert len(bytes.fromhex(meta["derived_key"])) == 32
    # 盐随机：两次哈希不同
    assert svc.hash_password(PW)["derived_key"] != meta["derived_key"]


async def test_verify_against_tampered_meta():
    meta = svc.hash_password(PW)
    assert svc.verify_password_against(PW, meta)
    assert not svc.verify_password_against(PW, {**meta, "derived_key": "00" * 32})
    assert not svc.verify_password_against(PW, {"algorithm": "md5"})
    assert not svc.verify_password_against(PW, {"algorithm": "scrypt"})  # 缺字段


async def test_verify_requires_init(db):
    with pytest.raises(svc.AdminNotInitialized):
        await svc.verify_admin_password(db, PW)


# ---------- 会话存储 ----------

class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_session_lifecycle():
    clk = FakeClock()
    store = SessionStore(ttl_seconds=100, now_fn=clk)
    s = store.create()
    assert len(s.session_id) >= 32 and s.session_id != store.create().session_id
    state, got = store.lookup(s.session_id)
    assert state == "valid" and got.session_id == s.session_id
    assert got.created_at == 1000.0 and got.expires_at == 1100.0
    store.delete(s.session_id)
    assert store.lookup(s.session_id) == ("missing", None)
    assert store.get("never-existed") is None


def test_session_expiry_lazy_cleanup():
    clk = FakeClock()
    store = SessionStore(ttl_seconds=100, now_fn=clk)
    s = store.create()
    clk.t += 99
    assert store.lookup(s.session_id)[0] == "valid"
    clk.t += 1                      # 到达绝对过期点
    assert store.lookup(s.session_id) == ("expired", None)
    assert store.lookup(s.session_id)[0] == "missing"   # 已懒清理


# ---------- 登录限速 ----------

def test_rate_limit_window_and_reset():
    clk = FakeClock()
    lim = LoginRateLimiter(max_failures=5, window_seconds=300, now_fn=clk)
    assert not lim.blocked("ip1")
    for _ in range(5):
        lim.record_failure("ip1")
    assert lim.blocked("ip1")
    assert not lim.blocked("ip2")           # 按来源隔离
    lim.reset("ip1")
    assert not lim.blocked("ip1")
    for _ in range(5):                      # 成功登录清零后重新计
        lim.record_failure("ip1")
    assert lim.blocked("ip1")


def test_rate_limit_window_expiry():
    clk = FakeClock()
    lim = LoginRateLimiter(max_failures=5, window_seconds=300, now_fn=clk)
    for _ in range(5):
        lim.record_failure("ip1")
    assert lim.blocked("ip1")
    clk.t += 301                            # 窗口滑出
    assert not lim.blocked("ip1")
