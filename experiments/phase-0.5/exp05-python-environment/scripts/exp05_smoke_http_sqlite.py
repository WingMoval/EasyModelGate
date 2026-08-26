#!/usr/bin/env python
"""EXP-05 F+G: minimal HTTP smoke (uvicorn+FastAPI+httpx) and SQLite WAL smoke."""
import asyncio
import json
import socket
import sys
import tempfile
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

HERE = Path(__file__).resolve().parent.parent
PORT = 19090


def free_port(p):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", p))
        return True
    except OSError:
        return False
    finally:
        s.close()


async def http_smoke():
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    cfg = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(cfg)
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.1)
    async with httpx.AsyncClient() as c:
        r = await c.get(f"http://127.0.0.1:{PORT}/health", timeout=5.0)
        out = {"status_code": r.status_code, "body": r.json()}
    server.should_exit = True
    await task
    return out


async def sqlite_smoke():
    import aiosqlite
    import sqlite3

    tmp = Path(tempfile.mkdtemp(prefix="emg-exp05-")) / "test.db"
    res = {"sqlite_lib_version": sqlite3.sqlite_version}
    db = await aiosqlite.connect(tmp)
    try:
        cur = await db.execute("PRAGMA journal_mode=WAL")
        res["journal_mode"] = (await cur.fetchone())[0]
        await db.execute("PRAGMA busy_timeout=5000")
        cur = await db.execute("PRAGMA synchronous=NORMAL")
        await cur.fetchall()
        await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        await db.execute("INSERT INTO t (v) VALUES ('hello')")
        await db.commit()
    finally:
        await db.close()
    db = await aiosqlite.connect(tmp)
    try:
        cur = await db.execute("SELECT v FROM t WHERE id=1")
        row = await cur.fetchone()
        res["reopened_select_value"] = row[0]
        cur = await db.execute("PRAGMA journal_mode")
        res["journal_mode_after_reopen"] = (await cur.fetchone())[0]
    finally:
        await db.close()
    return res


async def main():
    assert free_port(PORT), f"port {PORT} busy"
    out = {"http_smoke": await http_smoke(), "sqlite_smoke": await sqlite_smoke()}
    (HERE.parent / "exp05-python-environment" / "smoke_results.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
