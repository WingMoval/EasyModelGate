"""共享 fixture：临时配置、fake 上游、TestClient、DB 种子工具。"""
from __future__ import annotations

import hashlib
import socket
import sqlite3
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR / "fake_upstream"))

from server import MODELS_PAYLOAD, create_fake_llama_app  # noqa: E402

from easymodelgate.app import create_app  # noqa: E402
from easymodelgate.config import (AppConfig, DatabaseConfig, LimitsConfig,  # noqa: E402
                                  SecurityConfig, ServerConfig, TimeoutsConfig,
                                  UpstreamConfig, UsageConfig)

FAKE_UPSTREAM_KEY = "sk-test-upstream"


def make_cfg(db_path: str | Path, upstream_base: str, *, slots: int = 1) -> AppConfig:
    return AppConfig(
        server=ServerConfig(host="127.0.0.1", port=3000),
        database=DatabaseConfig(path=str(db_path)),
        upstream=UpstreamConfig(base_url=upstream_base, api_key_file="",
                                slots=slots),
        timeouts=TimeoutsConfig(),
        security=SecurityConfig(),
        usage=UsageConfig(),
        limits=LimitsConfig(),
    )


@pytest.fixture()
def cfg_factory(tmp_path):
    return lambda upstream_base="http://up.invalid", **kw: make_cfg(
        tmp_path / "test.db", upstream_base, **kw)


@pytest.fixture(scope="session")
def fake_llama():
    app = create_fake_llama_app(require_key=FAKE_UPSTREAM_KEY)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "fake llama 启动失败"
    yield {"base_url": f"http://127.0.0.1:{port}", "api_key": FAKE_UPSTREAM_KEY,
           "app": app}
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def client(monkeypatch, fake_llama, cfg_factory):
    monkeypatch.setenv("EMG_UPSTREAM_API_KEY", fake_llama["api_key"])
    cfg = cfg_factory(upstream_base=fake_llama["base_url"])
    with TestClient(create_app(cfg)) as c:
        c.cfg = cfg          # type: ignore[attr-defined]
        c.fake_app = fake_llama["app"]  # type: ignore[attr-defined]
        yield c


def seed_key(db_path, token: str, *, username="alice", enabled=1,
             expires_at=None) -> int:
    """直接向库内写入一条可用 Key（绕过 CLI，便于鉴权测试）。"""
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            "INSERT OR IGNORE INTO users (username, enabled, created_at) VALUES (?,1,?)",
            (username, int(time.time() * 1000)))
        uid = con.execute("SELECT id FROM users WHERE username=?",
                          (username,)).fetchone()[0]
        cur = con.execute(
            """INSERT INTO api_keys
                 (user_id, name, key_prefix, key_hash, enabled, expires_at,
                  rpm_limit, token_limit, token_used, created_at, last_used_at)
               VALUES (?,?,?,?,?,?,?,?,0,?,NULL)""",
            (uid, "test", token[:12],
             hashlib.sha256(token.encode()).hexdigest(), enabled,
             expires_at, None, None, int(time.time() * 1000)))
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


VALID_TOKEN = "emg_" + "A1b2C3d4" + "IntegrationTestToken000000000"


@pytest.fixture()
def seeded(client):
    """已注入上游密钥的 client + 一条有效 emg_ Key；返回 (client, headers)。"""
    seed_key(client.cfg.database.path, VALID_TOKEN)
    return client, {"Authorization": f"Bearer {VALID_TOKEN}"}


def wait_latest_log(db_path, timeout: float = 5.0):
    """轮询等待 detached 日志任务落库，返回最新一行（dict）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        try:
            row = con.execute(
                "SELECT * FROM request_logs ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            con.close()
        if row is not None:
            return dict(row)
        time.sleep(0.05)
    return None


def init_schema(db_path) -> None:
    """同步初始化 schema（可在事件循环内安全调用）。"""
    import json

    from easymodelgate.db.database import SCHEMA_PATH, SCHEMA_VERSION

    Path(str(db_path)).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    try:
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        con.execute(
            "INSERT OR IGNORE INTO settings (key, value_json) VALUES ('schema_version', ?)",
            (json.dumps(SCHEMA_VERSION),))
        con.commit()
    finally:
        con.close()


def run_server_in_thread(app, port: float | int):
    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=int(port),
                            log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn 线程启动失败"
    return server, thread


def stop_server(server, thread) -> None:
    server.should_exit = True
    thread.join(timeout=5)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
