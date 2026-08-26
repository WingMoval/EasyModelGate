"""API Key 生成、哈希与脱敏工具（规格 §20 / §21）。

- 完整 Key 形如 emg_<token_urlsafe(32)>
- 数据库仅存 key_prefix（emg_ + 前 8 位随机字符）与 key_hash = SHA-256(完整 Key)
- 日志展示一律使用 mask 输出，禁止出现完整 Key
"""
from __future__ import annotations

import hashlib
import secrets

RANDOM_BYTES = 32
PREFIX_DISPLAY_LEN = 12  # emg_ + 8 个随机字符，例如 emg_a1b2c3d4
MASK_HEAD_LEN = 8
MASK_TAIL_LEN = 4


def generate_key(prefix: str) -> tuple[str, str]:
    """生成新 Key。返回 (full_key, key_prefix)。完整 Key 仅此一次机会展示。"""
    full = f"{prefix}{secrets.token_urlsafe(RANDOM_BYTES)}"
    return full, full[:PREFIX_DISPLAY_LEN]


def hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def mask_key(key_or_prefix: str) -> str:
    """脱敏展示：emg_abcd****wxyz；过短时全部以 * 替代。"""
    s = key_or_prefix
    if len(s) < MASK_HEAD_LEN + 2:
        return "*" * len(s)
    return f"{s[:MASK_HEAD_LEN]}****{s[-MASK_TAIL_LEN:]}"
