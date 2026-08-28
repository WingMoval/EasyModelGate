"""v0.1.1 Task 1 单元测试：user/key/usage 共享服务层。

全部使用 tmp_path 临时 SQLite；Key 均为合成值。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from easymodelgate.db import dao
from easymodelgate.db.database import Database
from easymodelgate.services import key_service, usage_service, user_service
from easymodelgate.services.analytics import SummaryFilter

TZ = "Asia/Shanghai"


@pytest.fixture()
async def db(tmp_path):
    d = await Database(tmp_path / "svc.db").connect()
    try:
        yield d
    finally:
        await d.close()


async def _mk_user(db, name="alice"):
    return await user_service.create_user(db, name, name.title(), "note")


# ---------- UserService ----------

async def test_user_create_list(db):
    uid = await _mk_user(db)
    rows = await user_service.list_users(db)
    assert [r["id"] for r in rows] == [uid]
    assert rows[0]["username"] == "alice"
    assert rows[0]["display_name"] == "Alice"
    assert rows[0]["note"] == "note"
    assert rows[0]["enabled"] == 1


async def test_user_duplicate_raises(db):
    await _mk_user(db)
    with pytest.raises(user_service.UserAlreadyExists) as ei:
        await _mk_user(db)
    assert ei.value.username == "alice"


async def test_user_enable_disable(db):
    uid = await _mk_user(db)
    await user_service.set_user_enabled(db, "alice", False)
    assert (await dao.get_user_by_id(db, uid))["enabled"] == 0
    await user_service.set_user_enabled(db, "alice", True)
    assert (await dao.get_user_by_id(db, uid))["enabled"] == 1
    with pytest.raises(user_service.UserNotFound):
        await user_service.set_user_enabled(db, "ghost", True)
    with pytest.raises(user_service.UserNotFound):
        await user_service.require_user(db, "ghost")


# ---------- KeyService ----------

async def test_key_create_full_key_only_once(db):
    uid = await _mk_user(db)
    kid, full, masked = await key_service.create_key(
        db, user_id=uid, name="laptop", rpm=5, token_limit=100,
        expires_in_days=None, timezone=TZ, key_prefix="emg_")
    assert full.startswith("emg_") and len(full) > 20
    assert masked == f"{full[:8]}****{full[-4:]}" or "****" in masked
    row = await key_service.get_key(db, kid)
    assert row["key_prefix"] == full[:12]
    # 库内只有哈希与前缀；任何其它函数都无法恢复完整 Key
    assert full not in (row["key_hash"], row["key_prefix"], str(masked))
    import hashlib
    assert row["key_hash"] == hashlib.sha256(full.encode()).hexdigest()
    assert row["rpm_limit"] == 5 and row["token_limit"] == 100
    assert row["expires_at"] is None and row["enabled"] == 1


async def test_key_expires_in_days(db):
    uid = await _mk_user(db)
    kid, _, _ = await key_service.create_key(
        db, user_id=uid, name=None, rpm=None, token_limit=None,
        expires_in_days=30, timezone=TZ, key_prefix="emg_")
    row = await key_service.get_key(db, kid)
    expected = datetime.now(ZoneInfo(TZ)) + timedelta(days=30)
    assert abs(row["expires_at"] - expected.timestamp() * 1000) < 60_000


async def test_key_get_by_id_missing(db):
    with pytest.raises(key_service.KeyNotFound):
        await key_service.get_key(db, 999)


async def test_key_prefix_resolution(db):
    uid = await _mk_user(db)
    _, full, _ = await key_service.create_key(
        db, user_id=uid, name=None, rpm=None, token_limit=None,
        expires_in_days=None, timezone=TZ, key_prefix="emg_")
    row = await key_service.resolve_key_prefix(db, full[:12])
    assert row["key_prefix"] == full[:12]
    with pytest.raises(key_service.AmbiguousKeyPrefix) as ei:
        await key_service.resolve_key_prefix(db, "emg_nosuch12")
    assert ei.value.count == 0
    # 人工构造重复前缀 → count > 1
    await dao.create_api_key(db, user_id=uid, name=None,
                             key_prefix="emg_dup0001", key_hash="h1")
    await dao.create_api_key(db, user_id=uid, name=None,
                             key_prefix="emg_dup0001", key_hash="h2")
    with pytest.raises(key_service.AmbiguousKeyPrefix) as ei:
        await key_service.resolve_key_prefix(db, "emg_dup0001")
    assert ei.value.count == 2


async def test_key_enable_disable_by_id(db):
    uid = await _mk_user(db)
    kid, _, _ = await key_service.create_key(
        db, user_id=uid, name=None, rpm=None, token_limit=None,
        expires_in_days=None, timezone=TZ, key_prefix="emg_")
    await key_service.set_key_enabled(db, kid, False)
    assert (await key_service.get_key(db, kid))["enabled"] == 0
    await key_service.set_key_enabled(db, kid, True)
    assert (await key_service.get_key(db, kid))["enabled"] == 1
    with pytest.raises(key_service.KeyNotFound):
        await key_service.set_key_enabled(db, 999, True)


async def test_key_set_limits_semantics(db):
    uid = await _mk_user(db)
    kid, _, _ = await key_service.create_key(
        db, user_id=uid, name=None, rpm=5, token_limit=100,
        expires_in_days=None, timezone=TZ, key_prefix="emg_")
    # 数值：直接设置
    _, r, t = await key_service.set_key_limits(db, kid, rpm=9)
    assert (r, t) == (9, 100)                       # KEEP 保持原值
    # CLEAR：置 NULL
    _, r, t = await key_service.set_key_limits(
        db, kid, rpm=key_service.CLEAR, token_limit=key_service.CLEAR)
    assert (r, t) == (None, None)
    row = await key_service.get_key(db, kid)
    assert row["rpm_limit"] is None and row["token_limit"] is None
    # 全 KEEP：不变
    _, r, t = await key_service.set_key_limits(db, kid, token_limit=77)
    assert (r, t) == (None, 77)
    with pytest.raises(key_service.KeyNotFound):
        await key_service.set_key_limits(db, 999, rpm=1)


# ---------- UsageService ----------

async def _seed_logs(db, uid, kid):
    now_ms = int(time.time() * 1000)
    rows = [
        # (age_hours, model, status, total_tokens)
        (0.5, "alpha", 200, 10),
        (2.0, "beta", 200, 20),
        (30.0, "alpha", 500, 0),
    ]
    for i, (age, model, status, tok) in enumerate(rows):
        await db.conn.execute(
            """INSERT INTO request_logs
                 (request_id, user_id, api_key_id, backend_id, model, endpoint,
                  started_at, status_code, total_tokens, error_type)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (f"r{i}", uid, kid, 1, model, "/v1/chat/completions",
             now_ms - int(age * 3_600_000), status, tok,
             None if status == 200 else "upstream_error"))
    await db.conn.commit()
    return now_ms


async def test_period_today(db):
    uid = await _mk_user(db)
    kid, _, _ = await key_service.create_key(
        db, user_id=uid, name=None, rpm=None, token_limit=None,
        expires_in_days=None, timezone=TZ, key_prefix="emg_")
    # 以“今日午夜”为锚点造数，与运行时刻无关（避免 00:00-02:00 边界假失败）
    now = datetime.now(ZoneInfo(TZ))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    m_ms = int(midnight.timestamp() * 1000)
    rows = [(m_ms + 3_600_000, "alpha", 200, 10),        # 今天
            (m_ms + 2 * 3_600_000, "beta", 200, 20),     # 今天
            (m_ms - 3_600_000, "alpha", 500, 0)]         # 昨天
    for i, (ts, model, status, tok) in enumerate(rows):
        await db.conn.execute(
            """INSERT INTO request_logs
                 (request_id, user_id, api_key_id, backend_id, model, endpoint,
                  started_at, status_code, total_tokens, error_type)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (f"r{i}", uid, kid, 1, model, "/v1/chat/completions",
             ts, status, tok, None if status == 200 else "upstream_error"))
    await db.conn.commit()
    start, end, gb = usage_service.resolve_time_range("today", None, None, TZ)
    assert start == m_ms and end is None
    assert gb == "hour"
    f = SummaryFilter(start_ms=start, end_ms=end, granularity=gb, timezone=TZ)
    rows = await usage_service.summarize(db, f)
    total = rows[-1]
    assert total["bucket"] == "TOTAL"
    assert total["requests"] == 2               # 今天只有前两条


async def test_period_7d_and_custom_and_group_by(db):
    start, end, gb = usage_service.resolve_time_range("7d", None, None, TZ)
    assert gb == "day" and end is None
    now_ms = int(time.time() * 1000)
    assert abs((now_ms - 7 * 86_400_000) - start) < 5_000
    start, end, gb = usage_service.resolve_time_range(
        None, "2026-08-01 00:00", "2026-08-02 00:00", TZ)
    assert gb == "day"
    tz = ZoneInfo(TZ)
    assert start == int(datetime(2026, 8, 1, tzinfo=tz).timestamp() * 1000)
    assert end == int(datetime(2026, 8, 2, tzinfo=tz).timestamp() * 1000)
    start, end, gb = usage_service.resolve_time_range(None, None, None, TZ)
    assert (start, end, gb) == (None, None, "none")
    with pytest.raises(ValueError):
        usage_service.resolve_time_range("nope", None, None, TZ)


async def test_usage_filters_resolve(db):
    uid = await _mk_user(db)
    kid, full, _ = await key_service.create_key(
        db, user_id=uid, name=None, rpm=None, token_limit=None,
        expires_in_days=None, timezone=TZ, key_prefix="emg_")
    await _seed_logs(db, uid, kid)
    u_id, k_id = await usage_service.resolve_filters(
        db, username="alice", key_prefix=full[:12])
    assert (u_id, k_id) == (uid, kid)
    with pytest.raises(user_service.UserNotFound):
        await usage_service.resolve_filters(db, username="ghost")
    with pytest.raises(key_service.AmbiguousKeyPrefix):
        await usage_service.resolve_filters(db, key_prefix="emg_zzzzzzzzzz")
    # model 过滤走 analytics（复用，非第二套算法）
    f = SummaryFilter(model="alpha", granularity=None, timezone=TZ)
    rows = await usage_service.summarize(db, f)
    assert rows[-1]["requests"] == 2
