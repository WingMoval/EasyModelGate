"""SQLite 连接与初始化（aiosqlite，单连接串行写入）。

启动 PRAGMA（规格 §22）：journal_mode=WAL / busy_timeout=5000 / synchronous=NORMAL。
schema 幂等初始化：已存在库不破坏数据；版本不匹配则拒绝启动。
"""
from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = 1


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> "Database":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        cur = await self._conn.execute(
            "SELECT value_json FROM settings WHERE key='schema_version'")
        row = await cur.fetchone()
        if row is None:
            await self._conn.execute(
                "INSERT INTO settings (key, value_json) VALUES ('schema_version', ?)",
                (json.dumps(SCHEMA_VERSION),))
            await self._conn.commit()
        else:
            existing = json.loads(row["value_json"])
            if existing != SCHEMA_VERSION:
                await self.close()
                raise RuntimeError(
                    f"数据库 schema 版本不匹配：期望 {SCHEMA_VERSION}，实际 {existing}。"
                    "请走规格变更流程，不要手动修改。")
        return self

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database 未连接，请先调用 connect()")
        return self._conn
