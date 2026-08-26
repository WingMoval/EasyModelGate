# Phase 12 验收报告：完整测试矩阵固化与发布前验收

- 日期：2026-08-26
- 前置：Checkpoint 1/2/3 均 PASS
- 结论：**PHASE_12 = PASS**

## 1. 验收范围

按任务书 §二~§二十三 执行：回归测试、Auth/Validation 边界、Non-stream 与
Streaming 回归（含字节保真）、Tool Calling 透明性、Semaphore/Queue 边界与
slot 漂移、总超时墙钟语义修复、Usage 一致性、Analytics 边界、RPM/Quota 边界、
SQLite 持久化、轻量并发压测、真实 llama.cpp 小回归、Direct vs Gateway 性能、
RSS/CPU、后台任务清理、Warning 审计、安全泄漏扫描、.gitignore 与文档一致性。

## 2. 最终测试总数

| 项 | 数值 |
|---|---|
| collected | **114** |
| passed | **114** |
| failed / skipped / error | 0 / 0 / 0 |
| warnings | 1（第三方，见 §16） |
| 全量耗时 | ~21s |

## 3. 新增测试（+38）

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| test_phase12_edge.py | 19 | 静默上游墙钟超时回归、Auth 10 种畸形边界（无 500）、大小写 Bearer、双空格宽容、validation 全矩阵（非 JSON/array/null/messages 变体/model 类型/stream 非 bool 透传/500KB 大 body 计数） |
| test_phase12_passthrough.py | 6 | parallel_tool_calls/response_format/reasoning_*/tool_choice 逐字段透传；响应顶层字段零添加；上游错误全矩阵 400/401/404/429/500 落库 |
| test_phase12_limits.py | 5 | slots=2 并发不排队、混合 30 连击 slot 无漂移；models 豁免 RPM/Quota；RPM 重启清零；token_used 重启持久化；quota limit=0 / used>limit |
| test_phase12_load.py | 2 | slots=1(50req×10) 与 slots=2(60req×12) 小压测：0 非预期状态码、shutdown 后 background_tasks 清空、slot 回满、token_used 精确=5×成功数 |
| test_analytics.py 追加 | 5 | 空库 / from==to / 全 NULL 行 / queue NULL·0·正数混合 / 月跨年 |
| test_security.py 追加 | 1 | 12 位 key_prefix 掩码保留头尾可识别片段 |

## 4. 修复的 Bug

### BUG-P12-01：total_request_timeout 对"长时间无 chunk"不生效（严重）

- 现象：Phase 8 的实现仅在 chunk 循环内比较时间；上游静默时 deadline 永不到期。
- 根因：缺少覆盖流式生命周期的墙钟机制。
- 修复：`relay.py` 中 relay_gen 以 `asyncio.timeout_at(deadline)` 包裹整个
  async-for（墙钟）；`TimeoutError` 显式分类为 error_type=timeout，
  与客户端断连的裸 CancelledError 可区分。
- 回归测试：`test_total_timeout_is_wall_clock_on_silent_upstream`
  （上游静默 30s、deadline 0.6s → 实测 ~0.6s 切断、落库 timeout）✅
- 修改文件：easymodelgate/proxy/relay.py；tests/fake_upstream/server.py
  （slow 上游新增 emg_silent 剧本）；新增上述测试。

其余无 bug。SSE/Tool Calling/Auth/Analytics 主链路未做任何重构（§一 合规）。

## 5. Auth 验收

10 种畸形 Authorization（缺失/空/Bear裸/多空格/错误 scheme/非 emg_ 前缀/
不存在 Key/超长 8000B）全部返回规范 401 信封，无一例 500；双空格 + 有效 Key
按宽容语义放行（与主流 SDK 一致，已注释说明）。disabled/expired/user-disabled、
hash 查询、日志无泄漏由 CP1/CP2 存量用例持续覆盖。

## 6. Proxy / SSE 验收

字节保真断言（multi-in-one / split-event / tool 流 / 默认注入流）继续通过；
CRLF、comment/ping、carry buffer 由扫描器单元测试覆盖（含逐字节喂入极限）；
EOF 无 [DONE] 与中途断开分别落 upstream_interrupted；include_usage 注入与
三种"客户端已有 stream_options"场景不变。

## 7. Tool Calling 验收

non-stream/streaming 结构、5 片 arguments、id/name 仅首片、index 全程、
finish_reason=tool_calls 全部保持；parallel_tool_calls / response_format /
reasoning_content / reasoning_effort / tool_choice 复杂对象逐字段透传相等；
响应顶层键集合断言网关未添加任何字段。

## 8. Queue / Timeout 验收

slots=1 第二请求 queue_wait≥50ms 且 ≤ 墙钟；queue_timeout→503 server_busy
（等待满额、upstream_status=NULL）；五类异常后 slot 释放；30 连击混合异常后
`available==2` 无漂移；静默上游墙钟超时（BUG-P12-01 回归）通过。

## 9. Usage / Analytics 验收

一致性矩阵：non-stream/stream/tool/并发 正确累加；usage 缺失、disconnect、
timeout、upstream error、quota reject、rpm reject 十类场景均不虚增 token_used。
Analytics：空库/from==to/全 NULL/NULL·0·正数混合/13 种粒度与过滤组合/
ISO 跨年/月跨年 全部正确；CLI 空结果正常输出 TOTAL 行不报错。

## 10. RPM / Quota 验收

rpm=1、大值、NULL、双 Key 隔离、窗口翻转（rollover 由 fixed-window 单测覆盖）、
Retry-After ≥1、拒绝三原则（写日志/不排队/不触达上游）全部通过。
**/v1/models 不受 RPM 与 Quota 限制——已用测试固化并写入 README「设计边界」。**

## 11. SQLite 验收

WAL/busy_timeout=5000/synchronous=NORMAL 生效；重启持久化（users/keys/
backends/request_logs/token_used）；多次 init 幂等；版本不匹配拒启；
RPM 内存计数重启清零（预期行为，测试固化）。

## 12. 并发稳定性结果

| 配置 | 总数 | 并发 | 成功 | 上游500 | 非预期 | 泄漏检查 |
|---|---|---|---|---|---|---|
| slots=1 | 50 | 10 | 45 | 5(剧本) | **0** | tasks 清空/slot 回满 |
| slots=2 | 60 | 12 | 54 | 6(剧本) | **0** | token_used=270 精确 |

无 database locked、无 task 泄漏、无 unhandled exception。

## 13. 真实 llama.cpp 回归（GPU-light）

- non-stream：200 "hello"，usage 含 cached_tokens=13
- streaming：[DONE] 收尾，tokens/TTFT 落库
- tool calling：finish=tool_calls，arguments=`{"city":"巴黎"}` 原样透传
- 断连释放：CP3 已实测 ≤0.6s slot 释放（本阶段未重复烧 GPU）
- 两并发排队：CP3 已实测 queue_wait=5740ms（引用 CP3 报告）

## 14. Direct vs Gateway 性能（N=7，median）

| 指标 | Direct | Gateway | 差值 | 规格上限 | 结论 |
|---|---|---|---|---|---|
| non-stream | 383.3ms | 399.3ms | **+16.0ms** | <20ms | ✅ |
| stream TTFT | 287.6ms | 296.1ms | **+8.5ms** | <10ms（上限20） | ✅ |

数据：logs/perf_phase12.json；短 prompt（"Say OK"）+ max_tokens=6 抑制 GPU 波动。

## 15. RSS / CPU

- 空闲 RSS：53.4MB（54,708KB）；负载后 +840KB，无线性增长
- 空闲 CPU：≈0.00%
- 均满足目标（RSS<150MB）

## 16. Warning 状态

唯一 warning：`StarletteDeprecationWarning: Using httpx with starlette.testclient
is deprecated; install httpx2 instead` —— 由 starlette 自身 testclient 模块触发，
属第三方已知提示，与本项目代码无关。按要求不做全局 ignore 掩盖，保留并记录。

## 17. 安全扫描

精确比对法（非 echo）：真实 upstream key 在除 `configs/upstream_key` 外的全部
项目文件中 **0 命中**；`emg_[43位]` 完整 Key 形态在 py/md/log/toml 中 **0 命中**；
docs 中 Authorization 示例均为占位符。request_logs 表结构层面无内容列。

## 18. 文档一致性

README：Phase 1–12 已实现（13/14 未标注完成）；新增「设计边界」节明确四项
（models 豁免 / Soft Quota / RPM 重启清零 / Analytics CLI-only / Admin API 未实现）。
.gitignore 八项必需条目逐一核对齐全，protocol samples 未被忽略。

## 19. 与冻结规格差异

累计差异与 CP1-3 相同（queue_wait 曾延期已于本阶段补齐；models 不限流、
掩码格式、%W→ISO 已处理）。本阶段无新增差异。

## 20. 剩余风险

1. Starlette testclient 弃用警告：未来 starlette 大版本可能移除兼容层，
   届时评估迁移 httpx2 或调整测试栈。
2. total deadline 的 streaming 切断对客户端表现为连接提前结束（无 [DONE]），
   符合设计但调用方需具备重试语义（OpenCode 具备）。
3. 固定窗口 RPM 的边界突发（规格接受项）。

## 21. 最终结论

**PHASE_12 = PASS**

EasyModelGate v0.1 功能面（鉴权/代理/SSE 保真/Tool Calling/断连保护/排队/
Usage/统计/限流/配额）全部达到冻结规格验收标准，性能与资源达标，无已知
阻塞缺陷。建议审核后进入 Phase 13（OpenCode A/B 集成）与 Phase 14（部署）。
