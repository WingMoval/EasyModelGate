"""SQLite 行为测试：WAL、幂等初始化、重启持久化。"""
from __future__ import annotations

import sqlite3

import pytest

from easymodelgate.db.dao import create_user, get_user_by_username, now_ms
from easymodelgate.db.database import Database


async def test_wal_enabled(tmp_path):
    db = await Database(tmp_path / "a.db").connect()
    try:
        cur = await db.conn.execute("PRAGMA journal_mode")
        assert (await cur.fetchone())[0].lower() == "wal"
        cur = await db.conn.execute("PRAGMA busy_timeout")
        assert (await cur.fetchone())[0] == 5000
    finally:
        await db.close()


async def test_restart_persistence_and_idempotent_schema(tmp_path):
    path = tmp_path / "b.db"
    db1 = await Database(path).connect()
    uid = await create_user(db1, "persist-user")
    await db1.close()

    db2 = await Database(path).connect()
    try:
        user = await get_user_by_username(db2, "persist-user")
        assert user is not None and user["id"] == uid
        # 重复初始化不破坏数据
        cur = await db2.conn.execute("SELECT COUNT(*) FROM users")
        assert (await cur.fetchone())[0] == 1
        cur = await db2.conn.execute(
            "SELECT value_json FROM settings WHERE key='schema_version'")
        assert (await cur.fetchone())[0] == "1"
    finally:
        await db2.close()


async def test_auto_init_when_missing(tmp_path):
    path = tmp_path / "sub" / "dir" / "auto.db"
    assert not path.exists()
    db = await Database(path).connect()
    await db.close()
    assert path.exists()
    con = sqlite3.connect(str(path))
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"users", "api_keys", "backends", "request_logs", "settings"} <= tables


async def test_version_mismatch_refuses(tmp_path):
    path = tmp_path / "c.db"
    db = await Database(path).connect()
    await db.conn.execute("UPDATE settings SET value_json='999' "
                          "WHERE key='schema_version'")
    await db.conn.commit()
    await db.close()
    with pytest.raises(RuntimeError, match="schema 版本不匹配"):
        await Database(path).connect()
