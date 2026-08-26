"""配置加载：默认值 < TOML 文件 < 环境变量（EMG_<段>_<字段>）。

敏感信息（upstream API Key）不进入本模块的常规配置流，
由 AppConfig.upstream_api_key() 按优先级解析：环境变量 > secret 文件。
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 3000


@dataclass(frozen=True)
class DatabaseConfig:
    path: str = "data/easymodelgate.db"


@dataclass(frozen=True)
class UpstreamConfig:
    base_url: str = "http://127.0.0.1:8080"
    api_key_file: str = "configs/upstream_key"
    slots: int = 1


@dataclass(frozen=True)
class TimeoutsConfig:
    """规格 §37 冻结值；read=0 在 TOML 中表示 None（流式不限制）。

    queue_timeout：等待 upstream slot 的上限，超时返回 503 server_busy。
    total_request：覆盖 排队+upstream+streaming 全生命周期的总 deadline。
    """

    connect: float = 5.0
    write: float = 60.0
    read: float | None = None
    pool: float = 10.0
    total_request: float = 1800.0
    queue_timeout: float = 120.0


@dataclass(frozen=True)
class SecurityConfig:
    key_prefix: str = "emg_"


@dataclass(frozen=True)
class UsageConfig:
    timezone: str = "Asia/Shanghai"


@dataclass(frozen=True)
class LimitsConfig:
    max_client_concurrency: int = 64


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig = ServerConfig()
    database: DatabaseConfig = DatabaseConfig()
    upstream: UpstreamConfig = UpstreamConfig()
    timeouts: TimeoutsConfig = TimeoutsConfig()
    security: SecurityConfig = SecurityConfig()
    usage: UsageConfig = UsageConfig()
    limits: LimitsConfig = LimitsConfig()

    def upstream_api_key(self) -> str | None:
        """解析 upstream API Key：环境变量 > api_key_file。

        返回 None 表示上游未启用鉴权。绝不打印、记录 Key 内容。
        """
        env_val = os.environ.get("EMG_UPSTREAM_API_KEY", "").strip()
        if env_val:
            return env_val
        f = Path(self.upstream.api_key_file)
        try:
            if f.is_file():
                val = f.read_text(encoding="utf-8").strip()
                if val:
                    return val
        except OSError:
            pass
        return None


_SECTIONS: dict[str, type] = {
    "server": ServerConfig,
    "database": DatabaseConfig,
    "upstream": UpstreamConfig,
    "timeouts": TimeoutsConfig,
    "security": SecurityConfig,
    "usage": UsageConfig,
    "limits": LimitsConfig,
}


def load_config(path: str | os.PathLike | None = None) -> AppConfig:
    """按 默认 < TOML < 环境变量 的顺序合成配置。

    TOML 查找顺序：显式 path > 环境变量 EMG_CONFIG > configs/config.toml。
    """
    data: dict[str, Any] = {}
    candidates: list[Path] = []
    explicit = bool(path or os.environ.get("EMG_CONFIG"))
    if path:
        candidates.append(Path(path))
    elif os.environ.get("EMG_CONFIG"):
        candidates.append(Path(os.environ["EMG_CONFIG"]))
    else:
        candidates.append(Path("configs/config.toml"))
    for c in candidates:
        if c.is_file():
            data = tomllib.loads(c.read_text(encoding="utf-8"))
            break
    else:
        # 规格 §21（Phase 14）：配置缺失必须 fail-fast，
        # 禁止静默回落默认值后"看起来正常"地启动。
        tried = " -> ".join(str(c) for c in candidates)
        raise FileNotFoundError(
            f"配置文件未找到（已尝试：{tried}）。"
            "请先复制 configs/config.example.toml 为 configs/config.toml，"
            "或通过 --config / EMG_CONFIG 指定有效路径。")

    kwargs: dict[str, Any] = {}
    for section, cls in _SECTIONS.items():
        raw: dict[str, Any] = dict(data.get(section) or {})
        fields = cls.__dataclass_fields__
        for fname, field in fields.items():
            env_key = f"EMG_{section.upper()}_{fname.upper()}"
            if env_key in os.environ:
                raw[fname] = _coerce(fields[fname].type, os.environ[env_key])
        if section == "timeouts" and raw.get("read") == 0:
            raw["read"] = None  # TOML 无 null，约定 0 表示不限
        kwargs[section] = cls(**raw)
    return AppConfig(**kwargs)


def _coerce(annotation: Any, raw: str) -> Any:
    """环境变量字符串 → 字段类型（覆盖 int / float / Optional[float|None] / str）。"""
    text = str(annotation)
    if text == "int":
        return int(raw)
    if text in ("float", "float | None", "int | None"):
        return None if raw.strip() == "" or raw.strip().lower() == "none" else float(raw)
    if text == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return raw
