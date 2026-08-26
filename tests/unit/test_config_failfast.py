"""Phase 14 回归：显式配置缺失时必须 fail-fast（规格 §21）。"""
from __future__ import annotations

import pytest

from easymodelgate.config import load_config


def test_explicit_missing_config_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "not-exist.toml")


def test_env_missing_config_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("EMG_CONFIG", "/nonexistent/prod.toml")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_config(None)


def test_default_missing_config_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # 无 configs/config.toml
    monkeypatch.delenv("EMG_CONFIG", raising=False)
    with pytest.raises(FileNotFoundError):
        load_config(None)


def test_existing_config_still_loads(tmp_path):
    c = tmp_path / "ok.toml"
    c.write_text('[server]\nport = 3123\n')
    cfg = load_config(c)
    assert cfg.server.port == 3123
