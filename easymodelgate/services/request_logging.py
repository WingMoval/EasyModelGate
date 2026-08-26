"""request_logs 持久化服务（规格 §36 / Checkpoint 3 §二）。

调用方式：在 relay 的 finally 中经 app.state.spawn 创建 detached task
执行 persist_request_log —— 不阻塞、不受客户端断连取消影响。

数据一致性：
- request_logs INSERT 与 api_keys.token_used 原子累加在同一事务提交，
  避免并发 lost update；
- token 累加使用 SQL 侧 `token_used = token_used + ?`，绝不在 Python 求和；
- 仅当 total_tokens 可靠（upstream 返回 usage）时才累加；usage 缺失不估算。
"""
from __future__ import annotations

from typing import Any

from ..db.database import Database

MAX_ERROR_MESSAGE_LEN = 500

_COLUMNS: tuple[str, ...] = (
    "request_id", "user_id", "api_key_id", "backend_id", "model", "endpoint",
    "started_at", "finished_at", "duration_ms", "queue_wait_ms",
    "upstream_duration_ms", "ttft_ms",
    "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens",
    "stream", "finish_reason", "status_code", "upstream_status_code",
    "client_ip", "input_bytes", "output_bytes", "error_type", "error_message",
)


async def persist_request_log(
    db: Database,
    record: dict[str, Any],
    *,
    token_increment_for_key_id: int | None = None,
) -> None:
    """写入一条请求日志；可选地在同一事务内原子累加 token_used。"""
    values: list[Any] = []
    for col in _COLUMNS:
        v = record.get(col)
        if col == "error_message" and v is not None:
            v = str(v)[:MAX_ERROR_MESSAGE_LEN]
            v = v if v else None
        values.append(v)
    placeholders = ",".join("?" * len(_COLUMNS))
    await db.conn.execute(
        f"INSERT INTO request_logs ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
        values)

    total_tokens = record.get("total_tokens")
    if (token_increment_for_key_id is not None
            and isinstance(total_tokens, int) and total_tokens > 0):
        await db.conn.execute(
            "UPDATE api_keys SET token_used = token_used + ? WHERE id = ?",
            (total_tokens, token_increment_for_key_id))

    await db.conn.commit()
