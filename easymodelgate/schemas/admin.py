"""Admin API 请求/响应模型（v0.1.1 Task 3）。

响应模型显式列字段——敏感列（key_hash 等）从模型层面杜绝外泄。
时间字段契约：Unix 毫秒整数（与库内一致），NULL → JSON null。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AdminModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- users ----------

class AdminUserCreateRequest(AdminModel):
    username: str
    display_name: str | None = None
    note: str | None = None


class AdminUserResponse(AdminModel):
    id: int
    username: str
    display_name: str | None
    note: str | None
    enabled: bool
    created_at: int


class AdminUserListResponse(AdminModel):
    items: list[AdminUserResponse]


# ---------- keys ----------

class AdminKeyCreateRequest(AdminModel):
    user_id: int
    name: str | None = None
    rpm: int | None = None
    token_limit: int | None = None
    expires_in_days: int | None = None


class AdminKeyResponse(AdminModel):
    id: int
    user_id: int
    username: str | None
    name: str | None
    key_prefix: str
    masked_key: str
    enabled: bool
    rpm: int | None          # rpm_limit；null=不限
    token_used: int
    token_limit: int | None  # null=不限
    expires_at: int | None
    last_used_at: int | None


class AdminKeyCreateResponse(AdminModel):
    key: AdminKeyResponse
    api_key: str             # 完整 Key 仅此一次


class AdminKeyListResponse(AdminModel):
    items: list[AdminKeyResponse]


class AdminKeyLimitsRequest(AdminModel):
    """缺失字段=KEEP；显式 null=CLEAR；整数=SET（0/负数保持生产原样语义）。"""
    rpm: int | None = None
    token_limit: int | None = None
