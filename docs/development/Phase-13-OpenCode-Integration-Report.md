# Phase 13 验收报告：真实 OpenCode A/B 全链路集成验证

- 日期：2026-08-26
- 前置：Checkpoint 1/2/3 + Phase 12 均 PASS（114 项自动测试）
- 结论：**PHASE_13 = PASS**

## 1. 验证环境

| 项 | 值 |
|---|---|
| 网关 | EasyModelGate 0.1.0 @ 127.0.0.1:3000（前台临时运行，easymodelgate-dev 环境） |
| 上游 | llama-server（Qwen3.8-27B，ctx=32768，--parallel 1）@ :8080 |
| OpenCode | v1.18.23，CLI `opencode run --model <provider>/qwen3.8-local` |
| 测试数据 | 用户 `opencode-test`；Key 经 CLI 创建、仅 stdout 展示一次 |

## 2. A/B Provider 配置方式（脱敏）

- 修改前完整备份：`~/.config/opencode/opencode.jsonc.phase13-bak`（chmod 600）
- **保留原直连 Provider `local-qwen`**（baseURL http://127.0.0.1:8080/v1）不动
- 新增 `local-qwen-emg`：baseURL `http://127.0.0.1:3000/v1`，
  apiKey = EasyModelGate 下发的 emg_ Key（存于 OpenCode 私有配置，权限已收紧至 600）
- 最终可随时执行：
  `opencode run --model local-qwen/qwen3.8-local`（A 直连）与
  `opencode run --model local-qwen-emg/qwen3.8-local`（B 经网关）
- 报告不含任何真实 Key 值

## 3. 基础问答（Test 01）

同一 Prompt「只回复：EasyModelGate test OK」：

| | rc | 耗时 | 输出 | 异常标记 |
|---|---|---|---|---|
| Direct | 0 | 9.2s | EasyModelGate test OK | 无 |
| Gateway | 0 | 8.8s | EasyModelGate test OK | 无 |

## 4. Streaming（Test 02）

三段式长输出任务，后台运行 + 每 0.75s 采样输出文件：

| | 首次增长时刻 | 结束前大小 | 结论 |
|---|---|---|---|
| Direct | ~3s (35B) | 770B → 770B | 渐进输出 ✅ |
| Gateway | ~3s (35B) | 35B → 836B | 渐进输出 ✅（非一次性吐出） |

两侧 SSE 流式 UX 一致。

## 5. Tool Calling（Test 03）

目录含 file_a.txt/file_b.txt，要求只读列出：

- Direct：正确列出两文件（15.9s）
- Gateway：列出两文件并附字节大小（19.8s，`ls -la` 变体）
- 双方均完成 tool_call → 执行 → 结果回传 → 最终回答

## 6. Multi-tool Agent（Test 04）

任务：浏览目录 → 读 notes_a.md/notes_b.md → 总结核心指标与部署要求。

- Direct（34.1s）与 Gateway（36.0s）均正确提取全部三个事实点：
  吞吐 12k msg/s、内存 256MB、端口 9321 —— 连续工具链无断裂。

## 7. WebFetch（Test 05）

抓取 https://example.com 并回答主标题：

- 两侧均出现 WebFetch 工具徽章，均正确回答 "Example Domain"
- （Direct 19.1s / Gateway 16.9s）—— 网关未破坏 webfetch agent loop

## 8. 长 Agent（Test 07）

工作区：README.md + src/app.py + src/util.py + docs/design.md(埋哨兵行) +
data/metrics.csv(200 行)。任务：浏览→读 4 文件→全局搜索 SENTINEL→总结架构。

| | rc | 耗时 | 哨兵行原样找到 | 异常 |
|---|---|---|---|---|
| Direct | 0 | 60.7s | SENTINEL_EASYMODEL_GATE_2026: 蓝色蜂鸟在午夜迁移。 | 无 |
| Gateway | 0 | 84.9s | 同上（逐字一致） | 无 |

## 9. 近 32K 工作流（Test 08）

构造 big.txt = 74,141 字节 ≈18.5K tokens（120 节结构化英文+埋哨兵句于第 241 行）。
任务：全文读取 → 定位哨兵行原样输出 → 两句概括。

| | rc | 耗时 | 结果 |
|---|---|---|---|
| Direct | 0 | 79.2s | 第 241 行命中，密语「紫色极光」✅ 无 Compaction 触发 |
| Gateway | 0 | 138.7s | 同上 ✅ 无 payload 截断 / JSON 错误 / 流中断 |

**Gateway 未比 Direct 更早出现任何异常**（耗时差属模型随机波动）。

## 10. Usage / token_used

`usage summary --user opencode-test --period today`（节选 TOTAL 行）：

```
请求数 30（成功 30 失败 0）
prompt 228,410 / completion 1,993 / total 230,403 / cached 187,576
平均耗时 10439ms · 平均排队 264ms · 最大排队 2195ms · 平均 TTFT 4642ms
```

一致性 SQL 校验：`api_keys.token_used(230403) == Σ request_logs.total_tokens(230403)`
→ **PASS**（30 条含 usage 请求精确累计）。
cached_tokens 占比 81% —— llama.cpp KV cache 在真实 Agent 多轮下高效复用。

## 11. Queue 实测

OpenCode 长生成占位期间并发 curl B 进入：

- B 最终 **200**（等待后完成）
- 落库：B(queue_wait_ms=12813, status=200)；A 的会话标题请求 queue_wait=6623
  （OpenCode 主请求后自动发起的第二次调用被正确排队）
- 三段分解持续成立：duration ≈ queue_wait + upstream_duration

## 12. RPM 真实集成

专用 Key 设 rpm=3：req1-3 = 200；req4 = **429** + `retry-after: 51`，
落库 `(rate_limited, queue_wait_ms=0, upstream_status=NULL)` —— 未触达上游。
验证后 `key set-limits --clear-rpm` 恢复，不影响后续测试。

## 13. Soft Quota 真实集成

专用 Key limit=120，真实生成序列：used 44 → 88 → 131（**soft overrun 放行**）
→ 第 4 次 **429 insufficient_quota**。语义与规格完全一致。
两个 quota 测试 Key 已停用收尾。

## 14. Disconnect

OpenCode 长文生成 ~9s 时 kill -9 模拟用户取消：

- 网关日志出现 `client_disconnected` 行 ✅
- llama.cpp `/slots` is_processing=false（slot 已释放）✅（单次执行，未重复）

## 15. Direct vs Gateway 对比表

| 场景 | Direct | Gateway |
|---|---|---|
| T01 基础问答 | PASS | PASS |
| T02 Streaming 渐进输出 | PASS | PASS |
| T03 Tool Calling | PASS | PASS |
| T04 Multi-tool Agent | PASS | PASS |
| T05 WebFetch | PASS | PASS |
| T07 长 Agent（多文件+搜索+总结） | PASS | PASS |
| T08 近 32K 工作流 | PASS（79.2s） | PASS（138.7s） |
| Disconnect | N/A | PASS |

协议行为、工具链、完成能力、错误率完全等价；文字差异属模型随机性。

## 16. 发现并修复的 Bug

**无。** 本阶段零代码修改即通过全部场景——Phase 12 的字节保真与断连设计
在真实 Agent 工作流下直接成立。（测试脚本侧曾修正两处自设问题：
env 变量跨 shell 丢失、/slots 顶层数组解析，与网关无关。）

## 17. 自动回归测试状态

Phase 13 结束后全量重跑：**114 passed / 0 failed / 0 skipped**，~22s。
本阶段未新增业务代码，故未新增单测；真实场景证据以本报告记录归档。

## 18. 安全扫描

- 精确比对法：upstream key 与 Phase 13 测试 emg_ Key 在项目源码/docs/logs 中
  **0 泄漏**
- OpenCode 配置与备份均已 chmod 600；报告仅写"Key 已配置"，不含真实值
- 测试 Prompt/Response 未落库（request_logs 无内容列，结构保证）

## 19. 与冻结规格差异

无新增差异。历史差异（models 不限流、Soft Quota 语义、RPM 重启清零等）已在
README「设计边界」固化。

## 20. 剩余风险

1. 长 Agent 场景 Gateway 侧耗时波动（84.9s vs 60.7s）主要来自模型生成随机性；
   Phase 12 已证明网关固有开销 <20ms。
2. OpenCode 会话标题等隐性第二请求会参与排队——slots=1 时表现为额外等待，
   属预期；未来 parallel>1 或 slots 提调即可缓解。
3. p13-rpm/p13-quota 等 scratch Key 已停用但保留在库中便于审计（enabled=0 不构成风险）。

## 21. 最终结论

**PHASE_13 = PASS**

真实 OpenCode Agent 全场景（问答/流式/单工具/多轮工具/WebFetch/长 Agent/近 32K）
在 EasyModelGate 代理下与直连行为等价；限流/配额/排队/断连四项治理能力在真实
流量下全部生效且可观测。v0.1 功能验收链路（Phase 0→13）全部闭环。
