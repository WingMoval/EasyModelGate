"""core.ratelimit 固定窗口单元测试。"""
from __future__ import annotations

from easymodelgate.core.ratelimit import FixedWindowRpmLimiter


def test_unlimited_always_allowed():
    limiter = FixedWindowRpmLimiter()
    for i in range(1000):
        ok, retry = limiter.check(1, None, now=i * 0.01)
        assert ok and retry == 0


def test_fixed_window_counts_within_window():
    limiter = FixedWindowRpmLimiter()
    t0 = 1_000_000.0  # 落在同一自然分钟窗口内
    for i in range(5):
        ok, _ = limiter.check(7, 5, now=t0 + i)
        assert ok, f"第 {i+1} 个请求不应被拒"
    ok, retry_after = limiter.check(7, 5, now=t0 + 6)
    assert not ok
    assert 1 <= retry_after <= 60


def test_window_reset_next_minute():
    limiter = FixedWindowRpmLimiter()
    # 选一个窗口内起点：floor(t/60)*60 == 999_960，窗口区间 [999960, 1000020)
    t0 = 1_000_000.0
    for i in range(3):
        assert limiter.check(9, 3, now=t0 + i)[0]
    assert not limiter.check(9, 3, now=t0 + 15)[0]   # 同窗口第 4 次 → 拒绝
    ok, _ = limiter.check(9, 3, now=t0 + 25)          # 已进入下一窗口 → 清零
    assert ok


def test_keys_isolated():
    limiter = FixedWindowRpmLimiter()
    for i in range(10):
        assert limiter.check(1, 10, now=500.0 + i)[0]
    assert not limiter.check(1, 10, now=510.0)[0]
    ok, _ = limiter.check(2, 10, now=511.0)
    assert ok
