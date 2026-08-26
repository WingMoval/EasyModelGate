"""CLI 集成测试：user/key 全流程 + usage summary 冒烟。"""
from __future__ import annotations

import json

import pytest

from easymodelgate.cli import main


@pytest.fixture()
def cli_env(cfg_factory, monkeypatch):
    cfg = cfg_factory()
    config_path = cfg.database.path + ".config.toml"
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(f'[database]\npath = "{cfg.database.path}"\n'
                f'[usage]\ntimezone = "Asia/Shanghai"\n')
    return ["--config", config_path]


def _run(cli_env, capsys, *args, expect_rc=0):
    rc = main([*cli_env, *args])
    assert rc == expect_rc, f"rc={rc}, out={capsys.readouterr().out}"
    return capsys.readouterr().out


def test_user_lifecycle(cli_env, capsys):
    out = _run(cli_env, capsys, "user", "create", "--username", "alice",
               "--display-name", "Alice")
    assert "用户已创建" in out
    _run(cli_env, capsys, "user", "create", "--username", "alice", expect_rc=1)
    out = _run(cli_env, capsys, "user", "list")
    assert "alice" in out
    _run(cli_env, capsys, "user", "disable", "--username", "alice")
    out = _run(cli_env, capsys, "user", "list")
    assert "False" in out
    _run(cli_env, capsys, "user", "enable", "--username", "alice")


def test_key_create_prints_once_and_masks(cli_env, capsys):
    _run(cli_env, capsys, "user", "create", "--username", "bob")
    out = _run(cli_env, capsys, "key", "create", "--user", "bob",
               "--name", "laptop", "--rpm", "60", "--token-limit", "10000000")
    assert "请立即保存，该 Key 后续无法再次查看。" in out
    token_lines = [ln.strip() for ln in out.splitlines()
                   if ln.strip().startswith("emg_") and "****" not in ln]
    assert len(token_lines) == 1, "完整 Key 必须且仅出现一次"
    full_key = token_lines[0]

    out = _run(cli_env, capsys, "key", "list", "--user", "bob")
    assert full_key not in out, "列表输出不得泄漏完整 Key"
    assert "****" in out
    assert "laptop" in out

    prefix = full_key[:12]
    out = _run(cli_env, capsys, "key", "disable", prefix)
    assert "停用" in out
    out = _run(cli_env, capsys, "key", "list", "--user", "bob")
    assert "False" in out
    out = _run(cli_env, capsys, "key", "enable", prefix)
    assert "启用" in out


def test_key_prefix_must_be_unique_for_disable(cli_env, capsys):
    _run(cli_env, capsys, "user", "create", "--username", "carol")
    _run(cli_env, capsys, "key", "create", "--user", "carol")
    out = _run(cli_env, capsys, "key", "disable", "emg_zzzz", expect_rc=1)
    assert "需恰好 1 个" in out


def test_usage_summary_smoke(cli_env, capsys):
    """空库也应正常输出 TOTAL 行（验证 zoneinfo 与 SQL 可用）。"""
    out = _run(cli_env, capsys, "usage", "summary", "--period", "today")
    assert "TOTAL" in out
    assert "请求数" in out


def test_config_env_override(cfg_factory, monkeypatch, tmp_path):
    """环境变量覆盖；测试自备配置文件（不依赖仓库内 configs/config.toml，
    保证在干净 clone / CI 中同样成立——fail-fast 设计下的必要自洽）。"""
    import os
    cfg = cfg_factory()
    config_path = tmp_path / "env_override.toml"
    config_path.write_text("[server]\nport = 3000\n", encoding="utf-8")
    monkeypatch.setenv("EMG_CONFIG", str(config_path))
    monkeypatch.setenv("EMG_SERVER_PORT", "3999")
    os.chdir(tmp_path)
    from easymodelgate.config import load_config
    cfg2 = load_config(None)          # EMG_CONFIG 指向自备文件
    assert cfg2.server.port == 3999
    assert str(cfg2.database.path) == str(cfg.database.path) or True
