"""Upstream 请求头构造（规格 §19）。

原则：
- 不转发客户端 Authorization（必须替换为 upstream key 或移除）
- 剔除 hop-by-hop 头与 Host/Content-Length
- 不发送 Accept-Encoding（显式 identity），确保 aiter_bytes() 即原始字节、无解压差异
- 白名单保留少量安全头
"""
from __future__ import annotations

_ALLOWED_CLIENT_HEADERS = ("accept", "user-agent", "x-request-id")


def build_upstream_headers(
    client_headers=None,
    upstream_api_key: str | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if client_headers is not None:
        for name in _ALLOWED_CLIENT_HEADERS:
            value = client_headers.get(name)
            if value:
                headers[name] = value
    headers["Accept-Encoding"] = "identity"
    if upstream_api_key:
        headers["Authorization"] = f"Bearer {upstream_api_key}"
    return headers
