"""core.security 单元测试。"""
from __future__ import annotations

import hashlib

from easymodelgate.core.security import generate_key, hash_key, mask_key


def test_generate_key_shape():
    full, prefix = generate_key("emg_")
    assert full.startswith("emg_")
    assert prefix == full[:12] and len(prefix) == 12
    body = full[len("emg_"):]
    # token_urlsafe(32) → 43 字符左右的高熵串
    assert len(body) >= 40
    assert "+" not in body and "/" not in body and "=" not in body


def test_generate_key_unique():
    seen = {generate_key("emg_")[0] for _ in range(100)}
    assert len(seen) == 100


def test_hash_key_deterministic_and_safe():
    _, p = generate_key("emg_")
    h1 = hash_key(p)
    h2 = hash_key(p)
    assert h1 == h2 == hashlib.sha256(p.encode()).hexdigest()
    assert h1 != p and len(h1) == 64


def test_mask_key_formats():
    full, _ = generate_key("emg_")
    masked = mask_key(full)
    assert masked.startswith(full[:8]) and masked.endswith(full[-4:])
    assert "****" in masked
    assert full not in masked
    assert mask_key("abc") == "***"
    # 12 位 key_prefix 应保留头尾可识别片段（Checkpoint 3 修复）
    p12 = full[:12]
    m12 = mask_key(p12)
    assert m12 == p12[:8] + "****" + p12[-4:]
    assert "****" in m12 and p12 not in m12
