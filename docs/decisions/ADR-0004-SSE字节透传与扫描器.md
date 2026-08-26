# ADR-0004：SSE 采用字节透传 + 只读增量扫描器

- 状态：已接受（2026-08-26）
- 关联规格：§13-§17；证据：EXP-02、docs/protocol/llamacpp/

## 背景

Phase 0.5 实测证明 TCP/HTTP chunk ≠ SSE event（一个 chunk 可含多个 event）；
httpx `aiter_lines()` 会剥离行终止符，迫使网关重建 SSE 流；
Tool Calling 的 arguments 以任意粒度分片到达，任何重新序列化都可能破坏
客户端拼接。

## 决策

正式 relay transport 使用 `resp.aiter_bytes()`：

```python
async for chunk in resp.aiter_bytes():
    scanner.feed(chunk)      # 只读旁路
    yield chunk              # 原始字节直接转发
```

- 扫描器维护 carry buffer，按 `\n\n` 切分完整 event，负责 TTFT/[DONE]/usage
  旁路提取；usage 检测先做子串匹配再 json.loads 单次解析。
- 禁止 aiter_lines 作为传输层；禁止 JSON parse→dump→重构。
- upstream 请求显式 Accept-Encoding: identity，保证 bytes 即原始内容。

## 后果

- 客户端收到的字节与上游完全一致（后续 Phase 7 用 bytes 相等断言验收）。
- 事件被拆分到两个 chunk 的场景（EXP-02 未观测到但理论存在）由 carry buffer 兜底。
