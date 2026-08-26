"""llama.cpp 上游客户端封装。

httpx AsyncClient 使用配置冻结的超时档位（规格 §37）；
upstream API Key 惰性解析并缓存（环境变量 > secret 文件，绝不记录内容）。
"""
from __future__ import annotations

import httpx

from ..config import AppConfig

_UNSET = object()


class UpstreamClient:
    def __init__(self, cfg: AppConfig) -> None:
        t = cfg.timeouts
        self.cfg = cfg
        self.client = httpx.AsyncClient(
            base_url=cfg.upstream.base_url,
            timeout=httpx.Timeout(connect=t.connect, write=t.write,
                                  read=t.read, pool=t.pool),
        )
        self._api_key: str | None | object = _UNSET

    async def aclose(self) -> None:
        await self.client.aclose()

    @property
    def api_key(self) -> str | None:
        """惰性解析一次；None 表示上游未启用鉴权。"""
        if self._api_key is _UNSET:
            self._api_key = self.cfg.upstream_api_key()
        return self._api_key  # type: ignore[return-value]
