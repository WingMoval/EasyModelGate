# Checkpoint 3 执行报告（Phase 8-11）

- 日期：2026-08-26
- 范围：Phase 8 Semaphore+Queue；Phase 9 Usage Accounting；Phase 10 Analytics；
        Phase 11 RPM + Token Soft Quota
- 结论：**完成，待审核**

## 1. Phase 8 Semaphore / Queue 结果

- 正式接线：`鉴权 → RPM → Token 额度 → Semaphore 排队 → Upstream → finally 释放`。
  `UpstreamSlots.acquire(timeout)` 重构为显式返回 queue_wait_ms（monotonic），
  队列超时抛 `SlotQueueTimeout`；`release()` 幂等（防双重释放破坏信号量计数）。
- 七类路径 slot 无泄漏均有自动化验证：正常完成、upstream 4xx/5xx、connection error、
  timeout、client disconnect、upstream interrupted、CancelledError
  （其中 disconnect/interrupt/timeout 走真实 uvicorn 栈测试）。

## 2. queue_wait_ms 结果

- monotonic 计算，定义 = 开始等待 slot → 获得 slot。
- 真实 llama.cpp 并发实测（slots=1，A 占位生成期间 B 进入）：
  `queue_wait_ms=5740`，且 `duration_ms(7519) ≈ queue(5740) + upstream(1778)`，
  三段分解与规格语义完全一致。
- 自动化断言第二请求 queue_wait_ms ≥ 50 且不超过墙钟上限。

## 3. total_request_timeout 结果

- 新增配置 `timeouts.queue_timeout=120s` 与既有 `total_request=1800s`；
  排队阶段取两者较小值为等待窗口；streaming 阶段在每个 chunk 转发前检查 deadline。
- 测试（短 deadline 注入）：非流式挂起上游 → 恰好在 0.6s 返回 504 timeout、
  上游日志出现 cancelled/finally；流式场景部分输出后切断并落库 error_type=timeout。
- HTTPX 保持 connect=5/write=60/read=None/pool=10，未用 read timeout 替代总 deadline。

## 4. Usage Accounting 结果

- queue_wait_ms 补全入库；ttft 仅流式统计（非流式 NULL）。
- token_used 累计规则：仅当 upstream usage 可靠（total_tokens>0）才累加；
  usage 缺失（include_usage=false / 断连 / 上游错误）一律不估算不累加（有专项测试）。
- **原子性**：request_logs INSERT 与 `UPDATE api_keys SET token_used=token_used+?`
  在同一事务提交；禁止 Python 侧读改写。
- 并发测试：8 并发请求各 5 tokens → 精确累计 40，无 lost update。

## 5. 并发 token_used 原子累计测试

见上；用例 `test_concurrent_token_used_atomic`（ASGI 同循环并发 gather）。

## 6. Analytics CLI 示例（真实数据输出节选）

```
$ easymodelgate usage summary --period today --group-by hour
时间段            请求数 成功 失败 prompt completion total cached 平均耗时ms 平均排队ms 最大排队ms 平均upstream ms 平均TTFT ms
2026-08-26T09:00     6    5    1     70        99   169     18    2782.3     956.7     5740.0       2189.8     3519.5
TOTAL               10    7    3    103       130   233     31    2657.5     956.7     5740.0       2314.0     1799.2

$ ... --from "2026-08-20 00:00" --to "2026-08-27 00:00" --group-by week
2026-W35   10  7  3 ...
```

新增指标列：成功/失败、平均/最大排队。过滤 --user/--key/--model 生效
（rpm-test Key 过滤断言 4 请求=3 成功+1 限流）。
CLI 新增 `key set-limits PREFIX [--rpm N] [--token-limit N] [--clear-*]`；
`key list` 增加用户名/token_used 列，绝不显示完整 Key 或 key_hash。

## 7. ISO Week / 时区边界测试

- 分桶改为 Python `datetime.isocalendar()`，废除 SQLite %W：
  2026-12-31→2026-W53、2027-01-04→2027-W01 跨年正确（单测覆盖）。
- Asia/Shanghai 午夜边界：UTC 15:59→沪 23:59 归前一日、UTC 16:00→次日，分桶正确。
- custom range 统一 [from, to) 半开区间（to 时刻请求不计入）已测。
- hour/month 粒度、cached_tokens 求和、avg/max queue_wait 均有单测。

## 8. RPM 结果

- NULL 不限流（12 连发全 200）；rpm=3 时前 3 次 200、第 4 次 429；
  信封 type=rate_limit_error / code=rate_limit_exceeded；**Retry-After: 39**（实测头）；
  不同 Key 计数隔离；拒绝请求 queue_wait_ms=0、upstream_status_code=NULL、
  fake 上游收到的最后一笔请求不变（证明未触达）。
- 真实 llama.cpp 复测：req1-3=200、req4=429 + retry-after:39。

## 9. Token Soft Quota 结果

- unlimited 不受 used 影响；used<limit 正常；used==limit（90/100 + 单次 20）
  允许完成后 used=110，下一请求 429 insufficient_quota（soft overrun 语义）✓；
  拒绝落库 quota_exceeded、queue_wait_ms=0、未触达 upstream ✓。

## 10. 自动测试总数

**76 passed / 0 failed**（CP2 存量 58 + 本阶段新增 18），~15s。
本阶段新增：Phase 8 ×5、Phase 11 ×7、Analytics ×6。

## 11. 与规格差异

1. RPM/Quota 当前仅在 `/v1/chat/completions` 强制执行；`/v1/models` 未计入限流
   （轻量元数据端点）。如需全覆盖属规格澄清事项。
2. Analytics 改为「范围内取行 + Python 分桶聚合」：牺牲少量大表扫描性能，
   换取 ISO 周正确性与零 SQL 时区硬编码（规格 §45 的 100 万行阈值前无影响）。
3. last_used_at 未做节流（规格 §八.7 要求，维持现状）。
4. Schema 保持 v1 未变（§八.9）。

## 12. 风险

1. 固定窗口边界瞬时突发最坏 2×RPM（规格已知接受项）。
2. streaming 中 total deadline 触发时按 chunk 粒度切断——若模型长时间不出 chunk，
   实际切断可能晚于 deadline 一个 chunk 间隔（当前上游每 token 必出 chunk，影响可忽略）。
3. 并发测试依赖单 aiosqlite 连接串行化写入；未来若引入连接池需重审事务策略。

## 13. 下一阶段建议

进入 Phase 12（完整自动测试矩阵补齐与固化）、Phase 13（真实 OpenCode A/B：
local-qwen-direct vs local-qwen-emg 双 provider 全场景）、Phase 14（systemd 部署单元 +
部署文档 docs/deployment/）。三者均无阻塞前置。
