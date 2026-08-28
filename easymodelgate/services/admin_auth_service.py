"""单管理员凭据服务：scrypt 派生密钥存储与校验（Web Foundation §11 冻结方案）。

- 凭据存放于现有 settings 表（key="admin.auth"），只存派生密钥，绝不存明文；
- hashlib.scrypt（标准库）+ secrets 随机盐 + hmac.compare_digest 恒定时间比较；
- 参数写入元数据，支持未来升级（algorithm/version 字段）；
- 不 print、不感知 HTTP。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from ..db import dao
from ..db.database import Database

SETTINGS_KEY = "admin.auth"
ALGORITHM = "scrypt"
METADATA_VERSION = 1
# scrypt 参数（RFC 7914 推荐工作因子；登录 ~50ms，参数存库便于升级）
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
DKLEN = 32
# OpenSSL 默认 maxmem（32MiB）低于 128*N*r 需求，必须显式放宽
SCRYPT_MAXMEM = 128 * SCRYPT_N * SCRYPT_R * SCRYPT_P + (1 << 20)


class EmptyPasswordError(ValueError):
    pass


class AdminAlreadyInitialized(Exception):
    pass


class AdminNotInitialized(Exception):
    pass


def hash_password(password: str) -> dict[str, Any]:
    """由明文密码生成可入库的凭据元数据（不含明文/可逆形式）。"""
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=DKLEN,
                        maxmem=SCRYPT_MAXMEM)
    return {
        "version": METADATA_VERSION,
        "algorithm": ALGORITHM,
        "salt": salt.hex(),
        "derived_key": dk.hex(),
        "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "dklen": DKLEN,
        "updated_at": dao.now_ms(),
    }


def verify_password_against(password: str, meta: dict[str, Any]) -> bool:
    if meta.get("algorithm") != ALGORITHM:
        return False
    try:
        salt = bytes.fromhex(meta["salt"])
        expected = bytes.fromhex(meta["derived_key"])
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=int(meta["n"]), r=int(meta["r"]),
                            p=int(meta["p"]), dklen=len(expected),
                            maxmem=SCRYPT_MAXMEM)
    except (KeyError, TypeError, ValueError):
        return False
    return hmac.compare_digest(dk, expected)


async def get_admin_auth(db: Database) -> dict[str, Any] | None:
    raw = await dao.get_setting(db, SETTINGS_KEY)
    if raw is None:
        return None
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return meta if isinstance(meta, dict) else None


async def is_admin_initialized(db: Database) -> bool:
    return await get_admin_auth(db) is not None


async def initialize_admin(db: Database, password: str) -> None:
    """首次初始化；已存在则拒绝（不静默覆盖）。空密码拒绝。"""
    if not password:
        raise EmptyPasswordError("password must not be empty")
    if await is_admin_initialized(db):
        raise AdminAlreadyInitialized()
    await dao.set_setting(db, SETTINGS_KEY,
                          json.dumps(hash_password(password)))


async def verify_admin_password(db: Database, password: str) -> bool:
    meta = await get_admin_auth(db)
    if meta is None:
        raise AdminNotInitialized()
    return verify_password_against(password, meta)
