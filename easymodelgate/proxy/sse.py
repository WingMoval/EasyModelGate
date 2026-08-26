"""只读增量 SSE 扫描器（ADR-0004，冻结规格 §14-§15）。

职责边界：
- 仅旁路观测：data event 计数（TTFT 依据）、[DONE]、usage、finish_reason
- 维护 carry buffer；按 \\n\\n 与 \\r\\n\\r\\n 双分隔符切分完整事件
- 绝不修改 transport 字节；不拼接 tool_calls；不做任何重序列化输出

性能约定：仅当事件字节包含 b'"usage"' 或非 null 的 b'"finish_reason"'
特征时才做一次 json.loads；普通 content chunk 不解析。
"""
from __future__ import annotations

import json


class SseScanner:
    def __init__(self) -> None:
        self._carry = b""
        self.data_events = 0          # 有效 data 事件数（TTFT 判定依据）
        self.saw_done = False         # 是否见到 [DONE]
        self.usage: dict | None = None
        self.finish_reason: str | None = None

    def feed(self, chunk: bytes) -> list[bytes]:
        """喂入原始字节；返回本次切出的完整事件字节（不含分隔符）。

        未构成完整事件的尾部保留在 carry buffer 中等待下一块。
        """
        self._carry += chunk
        events: list[bytes] = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            idx, dlen = cut
            event = self._carry[:idx]
            self._carry = self._carry[idx + dlen:]
            events.append(event)
            self._process(event)
        return events

    @property
    def incomplete_tail(self) -> bytes:
        """当前尚未成完整事件的 carry 内容（测试用）。"""
        return self._carry

    def _find_cut(self) -> tuple[int, int] | None:
        i_lf = self._carry.find(b"\n\n")
        i_crlf = self._carry.find(b"\r\n\r\n")
        candidates: list[tuple[int, int]] = []
        if i_lf != -1:
            candidates.append((i_lf, 2))
        if i_crlf != -1:
            candidates.append((i_crlf, 4))
        if not candidates:
            return None
        return min(candidates)

    def _process(self, event: bytes) -> None:
        """处理一个完整事件；多行事件时逐行处理 data: 字段（SSE 规范）。"""
        saw_data = False
        for raw_line in event.split(b"\n"):
            line = raw_line.rstrip(b"\r")
            if not line.startswith(b"data:"):
                continue  # 注释（ping）/ 空行 / 其它字段：忽略
            body = line[len(b"data:"):].strip()
            if not body:
                continue
            saw_data = True
            if body == b"[DONE]":
                self.saw_done = True
                continue
            self.data_events += 1
            self._extract(body)
        if saw_data:
            return

    def _extract(self, body: bytes) -> None:
        if b'"usage"' in body:
            try:
                obj = json.loads(body)
            except ValueError:
                obj = None
            if isinstance(obj, dict):
                usage = obj.get("usage")
                if isinstance(usage, dict):
                    self.usage = usage

        # finish_reason:null 出现在每个常规 chunk；仅在非 null 特征时才解析
        if b'"finish_reason"' in body and b'"finish_reason":null' not in body:
            try:
                obj = json.loads(body)
            except ValueError:
                return
            choices = obj.get("choices") or [{}]
            fr = choices[0].get("finish_reason")
            if isinstance(fr, str):
                self.finish_reason = fr
