# Checkpoint 2 执行报告（Phase 4-7）

- 日期：2026-08-26
- 范围：Phase 4 Non-stream Proxy；Phase 5 Streaming + SSE Scanner；
        Phase 6 Disconnect + Request Logging；Phase 7 Tool Calling 保真测试
- 结论：**完成，待审核**

## 1. 本阶段目标

将 `POST /v1/chat/completions` 从 501 占位升级为正式透明代理：
非流式与流式全链路、字节级保真、usage 注入与旁路统计、客户端断连传播、
请求日志落库、Tool Calling 完整性验证。

## 2. 完成内容

### Phase 4 Non-stream
- dict body + 最小校验（object / messages 非空对象数组 / model 若存在须为 str），
  其余字段全部保留（含 web_search_options、reasoning_effort 等未来字段，测试验证透传）
- 上游错误原 status + 原 body 透传（400/429/500 实测）；连接失败→502 connection_error、
  超时→504 timeout
- 旁路提取 usage（prompt/completion/total/cached_tokens）与 finish_reason

### Phase 5 Streaming
- 冻结方案落地：`resp.aiter_bytes()` 原始字节直接 yield；同一份副本喂 SseScanner；
  全程零 JSON 重序列化
- SseScanner：`\n\n` 与 `\r\n\r\n` 双分隔符、carry buffer 跨 chunk 拼接、
  多行事件逐行处理 data 字段、注释/ping 忽略（不计 TTFT）
- usage 注入：仅 stream=true 且 stream_options 整体缺失时注入 include_usage=true；
  客户端已有对象（含 false）一律不改；usage chunk 原样转发不 strip
- scanner 先做 b'"usage"' 子串探测再单次 json.loads；finish_reason 仅在
  非 null 特征出现时解析——普通 content chunk 不解析

### Phase 6 Disconnect + Logging
- EXP-04 模式：try / except CancelledError / except GeneratorExit /
  finally{ await resp.aclose(); spawn(持久化) }
- request_logs 经 detached task 写入（app.state.spawn + registry + shutdown flush≤5s），
  本阶段字段全数填充：request_id/user_id/api_key_id/backend_id/model/endpoint/
  started_at/finished_at/duration_ms/stream/finish_reason/status_code/
  upstream_status_code/四类 tokens/input_bytes/output_bytes/error_type/error_message
- **queue_wait_ms 暂为 NULL**（Semaphore 接线属 Phase 8，规格允许）；
  **upstream_duration_ms 与 ttft_ms 本阶段已可准确采集并已填充**
- 错误分类：client_disconnected / upstream_interrupted（含流中断与 EOF 无 [DONE]）/
  upstream_error / timeout / connection_error

### Phase 7 Tool Calling
- 网关零感知：不拼 arguments、不改 id/index/name、不解析 delta.tool_calls
- 以 Phase 0.5 实测的 5 片 arguments 模式构造 fake 剧本，bytes 相等断言通过

## 3. 新增 / 修改文件

新增：
```
easymodelgate/proxy/relay.py                 # 透明转发核心
tests/integration/test_chat_nonstream.py     # 7 用例
tests/integration/test_chat_stream.py        # 9 用例
tests/integration/test_disconnect_real.py    # 2 用例（真实 uvicorn 双线程栈）
tests/unit/test_sse_scanner.py               # 10 用例
tests/unit/test_usage_injection.py           # 5 用例
docs/development/Checkpoint-2-Report.md
```
修改：
```
easymodelgate/proxy/sse.py                   # 占位 → 正式扫描器实现
easymodelgate/services/request_logging.py    # 占位 → 正式持久化
easymodelgate/routers/public.py              # 501 占位移除，接入 relay
easymodelgate/app.py                         # backend_id 解析注入 app.state
easymodelgate/core/auth.py                   # 增加 DEBUG 生命周期日志
tests/fake_upstream/server.py                # v2：字节剧本/错误码/慢速上游
tests/conftest.py                            # seeded/wait_latest_log/init_schema 等
README.md                                    # 状态表更新（Phase 4-7 已实现）
```

## 4. 测试结果

- **58 passed / 0 failed**（CP1 存量 23 + 本阶段新增 35），耗时 ~5.8s
- 自动化矩阵覆盖审核要求全部 19 项：non-stream chat/usage/tool_calls、
  streaming byte passthrough、multi-events-in-one-chunk、split-event-across-chunks、
  carry buffer（含逐字节喂入极限用例）、usage chunk、include_usage 注入、
  existing stream_options 不修改、[DONE]、streaming tool_calls、fragmented arguments、
  client disconnect、request log after disconnect、上游 400/429/500/连接失败/超时、
  流中断 interrupted

## 5. SSE byte 保真验证结果

| 场景 | 断言 | 结果 |
|---|---|---|
| 默认流（注入后） | client bytes == fake 原始 bytes | 一致 |
| 一个 chunk 打包多 events | 同上 + 5 个 data 行 | 一致 |
| 一个 event 拆两个 chunks | 同上（carry buffer 兜底） | 一致 |
| 逐字节喂入扫描器（单元） | 事件全部还原、tail 为空 | 通过 |
| tool_calls 流（5 片） | 同上 + 分片按序出现 | 一致 |

## 6. Tool Calling 保真验证结果

- non-stream：tool_calls 结构、arguments 单字符串、finish_reason=tool_calls 原样透传
- streaming：5 片 `{` / `"city":"` / `Paris` / `"` / `}`，id/type/name 仅首片、
  index 全程携带，输出 bytes 与 upstream **完全相等**
- 日志侧仅记录 finish_reason=tool_calls 与 token 数，未触碰任何调用内容

## 7. Client Disconnect 验证结果

真实 uvicorn 双服务器栈（httpx 真 TCP → 网关线程 → 慢速上游线程）：

- 正常完成对照：DONE 到达、error_type=NULL、slow 上游 completed ✓
- 断连场景：客户端 0.6s 后 aclose →
  detached 日志落库 `error_type=client_disconnected` ✓
  慢速上游观测到 cancelled 且无 completed ✓
  （EXP-04 本地量测为 ~2ms 量级；本阶段以事件链与上限断言验收）

## 8. Request Logging 结果

真实 llama.cpp 三次实测的落库行（节选）：

| 类型 | finish_reason | prompt/completion/total | cached | ttft_ms | error_type |
|---|---|---|---|---|---|
| non-stream | stop | 17/2/19 | 13 | NULL | NULL |
| streaming 完整 | stop | 16/29/45 | 0 | 728 | NULL |
| streaming 断连 | NULL | NULL | NULL | 558/671 | client_disconnected |

隐私检查：request_logs 无内容类列；服务日志 grep 无完整 Key。

## 9. 真实 llama.cpp spot check

- 非流式：200，content="hello"，usage 含 cached_tokens=13
- 流式：32 个 data 行、末尾 [DONE]、tokens 16/29/45
- **断连 slot 释放**：长生成期间 `/slots` 显示 slot0 is_processing=true；
  客户端 2.5s 断开后 ≤0.6s 内变为 false —— GPU 即刻停止推理 ✓（仅执行一次）

## 10. 与规格差异

1. queue_wait_ms=NULL（Phase 8 Semaphore 接线后填充）——规格允许。
2. total_request_timeout（1800s）本阶段未强制执行：read=None 下挂起型超时由
   connect 超时与客户端断连兜底；统一 deadline 计划并入 Phase 8 的排队/生命周期管理。
3. 流式上游非 200 时采用"读全量后透传"而非流式转发错误体（错误体本身很小，
   行为对客户端等价）。
4. 新增 DEBUG 级 relay/auth 生命周期日志（默认关闭，不影响生产日志脱敏）。

## 11. 风险

1. GeneratorExit 分支依赖 ASGI 服务器行为差异（uvicorn=CancelledError 路径已实测；
   其他 ASGI 服务器未验证）。
2. last_used_at 每请求一次 UPDATE，高频下可能需要节流（Phase 9 观察）。
3. 上游 EOF 无 [DONE] 归类为 upstream_interrupted 属本阶段设计决定，
   如需区分"正常静默结束"需后续规格澄清。

## 12. 下一阶段建议

进入 Checkpoint 3（Phase 8-11）：Semaphore 接线 + queue_wait_ms 填充 →
Usage 指标完善（cached_tokens 分析口径）→ Analytics CLI 强化 →
RPM 固定窗口接入鉴权链 + Token 软额度。RPM/quota 所需的 limiter 与数据列已在
CP1/CP2 就绪，接线工作量可控。
