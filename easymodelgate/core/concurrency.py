"""Upstream 并发槽位（规格 §30/§33）。

对应 llama.cpp --parallel 的 asyncio.Semaphore 包装。
acquire(timeout) 返回排队耗时 queue_wait_ms（monotonic 计算），
队列超时抛出 SlotQueueTimeout（由调用方映射为 503 server_busy）。
释放必须由调用方在 finally 中调用 release()——所有退出路径均不得泄漏 slot。
"""
from __future__ import annotations

import asyncio
import time


class SlotQueueTimeout(Exception):
    """等待 upstream slot 超时。waited_ms 为已等待耗时。"""

    def __init__(self, waited_ms: float) -> None:
        super().__init__("upstream slot queue timeout")
        self.waited_ms = waited_ms


class UpstreamSlots:
    def __init__(self, slots: int) -> None:
        self._slots = slots
        self._sem = asyncio.Semaphore(slots)

    @property
    def slots(self) -> int:
        return self._slots

    async def acquire(self, timeout: float | None = None) -> float:
        """获得 slot；返回 queue_wait_ms（monotonic）。

        timeout=None 表示无限等待；超时抛 SlotQueueTimeout（此时未占用 slot）。
        """
        t0 = time.monotonic()
        try:
            if timeout is None:
                await self._sem.acquire()
            else:
                await asyncio.wait_for(self._sem.acquire(), timeout)
        except asyncio.TimeoutError:
            raise SlotQueueTimeout((time.monotonic() - t0) * 1000) from None
        return (time.monotonic() - t0) * 1000.0

    def release(self) -> None:
        self._sem.release()

    @property
    def available(self) -> int:
        """当前空闲 slot 数（监控/测试用）。"""
        return self._sem._value  # noqa: SLF001 — 仅内部测试使用
