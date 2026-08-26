"""内存版固定窗口 RPM 限流（规格 §41）。

按 api_key_id 每 60 秒（对齐自然分钟窗口）计数；
SQLite 只存 rpm_limit 配置，不存实时计数；进程重启后清零（规格接受）。
Phase 11 将把 check() 接入鉴权后的请求路径；此处先提供纯实现便于单测。
"""
from __future__ import annotations

import time


class FixedWindowRpmLimiter:
    WINDOW_SECONDS = 60

    def __init__(self) -> None:
        # key_id -> (window_start_epoch_sec, count)
        self._counters: dict[int, tuple[int, int]] = {}

    def check(self, key_id: int, limit: int | None,
              now: float | None = None) -> tuple[bool, int]:
        """返回 (是否允许, Retry-After 秒)。limit 为 None 表示不限。"""
        if limit is None:
            return True, 0
        t = time.time() if now is None else now
        window_start = int(t // self.WINDOW_SECONDS) * self.WINDOW_SECONDS
        window_end = window_start + self.WINDOW_SECONDS
        cur_start, count = self._counters.get(key_id, (window_start, 0))
        if cur_start != window_start:
            cur_start, count = window_start, 0
        count += 1
        self._counters[key_id] = (cur_start, count)
        if count > limit:
            return False, max(1, int(window_end - t) + 1)
        return True, 0

    def reset(self) -> None:
        self._counters.clear()
