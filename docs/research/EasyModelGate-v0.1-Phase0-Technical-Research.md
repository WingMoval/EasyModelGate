# EasyModelGate v0.1 Phase 0 技术调研与架构建议

- Project: EasyModelGate
- Phase: 0
- Status: Completed / Reviewed
- Date: 2026-08-26
- Purpose: v0.1 开发前同类项目与关键技术调研
- Next Phase: Phase 0.5 协议与环境专项实测

---

## 1. 执行摘要

- **结论先行：适合立即开始 v0.1 开发。** 技术路线无重大不确定性：FastAPI + httpx.AsyncClient + uvicorn + aiosqlite + SQLite(WAL) 的组合被同类项目反复验证。
- **SSE 核心决策**：采用「按行透传 + 旁路嗅探」——不重新序列化 chunk（你的倾向**正确**），但需要逐行扫描以捕获 `usage`、`[DONE]`、TTFT 和客户端断连。new-api 与 litellm 都是"解析后重发"，但它们有跨供应商归一化需求；单后端网关没有，因此可以比它们更轻。
- **Token Usage 关键发现**：llama.cpp 自 PR #16052（2025-09 合并）起，仅在请求含 `"stream_options":{"include_usage":true}` 时才在流末尾发送 `choices:[]` + `usage` 块（issue #16048 记录了精确格式）。**方案 C（注入 include_usage + 单遍旁路解析）是零成本官方机制**，无需 tokenize、无需缓存流。
- **API Key 安全**：new-api 在 DB 明文存 key（反面教材）；litellm 用 `sha256(token).hexdigest()` 存哈希、查询时对呈现的 key 做同样哈希后等值查找（业界正确做法，与 GitHub/GitLab PAT 一致）。EasyModelGate 采用 `key_prefix + SHA-256 hash`，不需要 salt/bcrypt/argon2（高熵随机串）。
- **许可证风险提示**：你指定的 new-api 与 croit/llm-gateway 均为 **AGPL-3.0**，只能学习设计与接口行为，**不可复制代码**；one-api/litellm(核心)/Portkey 为 MIT，参考自由度高。
- **最重要的工程细节**：httpx 默认超时是全维度 5 秒（官方文档确认），直接用必然杀死长推理请求；Starlette 的 StreamingResponse 内建客户端断连监听并在断开时取消你的转发生成器——在生成器清理路径里 `await upstream.aclose()` 即可让 llama.cpp 及时中止 GPU 推理。

---

## 2. 参考项目列表

| 项目 | 语言 | License | 活跃度（2026-08-25 实测 GitHub API） | 参考价值 |
|---|---|---|---|---|
| QuantumNous/new-api | Go | **AGPL-3.0 ⚠️ 禁止复制代码** | 46,240★，最近 push 2026-08-24，极活跃 | 高：StreamScannerHandler（relay/helper/stream_scanner.go）、TokenAuth 中间件、token.go 字段设计 |
| BerriAI/litellm | Python | **MIT**（`enterprise/` 目录除外，双许可结构） | 57,247★，push 于当天，极活跃 | 高：`hash_token`（proxy/utils.py:3552）、spend_logs 异步批量写、并行限流 hook |
| songquanpeng/one-api（补充①） | Go | MIT | 36,574★，最后 push 2026-01（放缓） | 中：new-api 前身，结构更简单，MIT 可放心读设计 |
| Portkey-AI/gateway（补充②） | TypeScript | MIT | 12,821★，push 2026-05 | 中：轻量代理形态、retry/fallback/stream 设计思想 |
| croit/llm-gateway | Rust | **AGPL-3.0 ⚠️** | 16★，2026-06 新仓库，活跃但小众 | 低-中：仅产品形态参考（agent 化/RBAC 方向），不作为代码参考 |
| ggml-org/llama.cpp tools/server（上游权威） | C++ | MIT | 极活跃 | 最高：wire format 权威（include_usage 行为、sse-ping、tool calling、错误格式） |

> 补充项目选择理由：Portkey（轻量、MIT、OpenAI-compatible 代理形态最接近 EMG）；one-api（new-api 的 MIT 上游，读它可规避 AGPL 心智负担）。另在搜索中发现 `airnsk/proxycache`（专为 llama.cpp 的 OpenAI 兼容代理，53★，无 license）仅作旁证，未列入正式参考。

**实现方式冲突清单（不同项目做法不一致处，均如实列出）：**
1. Key 存储：new-api 明文 vs litellm SHA-256 哈希 → 选 litellm 模式。
2. SSE：new-api/litellm 解析后重建输出 vs 纯字节 passthrough → 折中选"行透传+旁路嗅探"。
3. 流式 usage：llama.cpp opt-in（默认不发）vs litellm 总是自己算/重建 → opt-in 注入。
4. 断连处理：new-api 显式监听 request context done（Go/gin 需手动）vs Starlette 自动取消生成器 → 用框架内建机制 + finally 清理。
5. 限流计数存储：litellm 内存+可选 Redis 同步 vs new-api Redis/内存 → 单实例选纯内存。

---

## 3. SSE Streaming 调研结论（最高优先级）

链路：`OpenCode → EasyModelGate(FastAPI) → httpx stream → llama.cpp :8080`。逐问回答：

1. **解析还是 passthrough？** 三种流派：① new-api：`bufio.Scanner(bufio.ScanLines)` 逐行扫，提取 `data:` 后内容送 `dataHandler` 回调再写出（relay/helper/stream_scanner.go，实测源码）；② litellm：完全 JSON 解析并重建 chunk（因要跨 100+ provider 归一化）；③ 纯字节 passthrough。**EMG 推荐：按行透传**——读到什么行就原样写出该行，同时做旁路检查（是否 `[DONE]`、是否含 `"usage"`、首 chunk 计时）。既保真又不瞎。
2. **用什么？** FastAPI `StreamingResponse(async generator, media_type="text/event-stream")` + `httpx.AsyncClient.stream("POST", ...)` 配合 `response.aiter_lines()`。这是 litellm 同款组合。
3. **Content-Type 保持？** 由 EMG 自己显式设置 `text/event-stream`；不要复制 upstream 响应头集合（会带上 hop-by-hop 头和 content-length 冲突），只挑 `content-type` 或直接写死。
4. **[DONE]**：原样透传给客户端（OpenCode 依赖它结束流）；EMG 内部收到后置完成标志、停止读 upstream 并关闭。new-api 收到 `[DONE]` 即 return 结束 scanner（同策略）。
5. **upstream 非 200**：必须在开始向客户端写之前检查 `resp.status_code`（httpx stream 模式天然支持：先拿到响应头/状态，再决定怎么读 body）。非 200 时以相同状态码返回 upstream 的错误 body（llama.cpp 已是 OpenAI 风格 `{"error":{...}}`），此时响应不是 SSE，Content-Type 用 upstream 的 application/json。
6. **upstream 中断**（EOF 无 [DONE] / 读异常）：new-api 维护了完整的 `StreamEndReason` 分类（Done/EOF/ScannerErr/Timeout/Panic/PingFail/ClientGone）。EMG 简化版：把已收到的 chunks 转发完后终止连接，记录 `error_type='upstream_interrupted'`。不建议伪造 [DONE]（客户端可能误认为正常完成）。
7. **client 主动断开**：见 §12 详细机制——必须取消 upstream。new-api 源码注释原文即为此设计："*客户端断开：立即 cleanup 关闭上游 resp.Body…避免为已放弃的请求继续消费上游 token*"——这正是你担心的 GPU 空算问题，同类项目已验证此为必做项。
8. **Cache-Control: no-cache**：建议加（SSE 惯例头，防中间层缓存）。
9. **Connection: keep-alive**：不需要手动设置（HTTP/1.1 默认持久连接；且 Connection 是 hop-by-hop 头，本就不应透传）。
10. **关 proxy buffering**：uvicorn 自身不缓冲；若未来前面加 nginx 必须配 `proxy_buffering off`（或响应加 `X-Accel-Buffering: no`）。v0.1 直连无需处理，但建议顺手加上该头，成本为零。另外 llama.cpp 自带 `--sse-ping-interval`（默认 30s 发 SSE 注释行防 idle 断连），上游已解决 keepalive 问题，网关不必自造 ping。
11. **Streaming usage 何时出现 & 如何记录**：
    - 非 streaming：响应 JSON 尾部 `usage` 对象总是存在。
    - streaming：**只有**请求带 `stream_options.include_usage=true` 才有；出现形式为一个特殊末尾块：`{"choices":[],"created":...,"id":...,"model":...,"object":"chat.completion.chunk","usage":{"prompt_tokens":75,"completion_tokens":31,"total_tokens":106},"timings":{...}}`，随后才是 `data: [DONE]`（issue #16048 原始记录）。
    - 记录方法：转发循环中对每行做 `line.startswith('data:')` 前缀检查；当行内容含 `"usage"` 且含 `"choices":[]` 特征时做一次 `json.loads` 提取三个数字（每请求最多发生一次完整解析，纳秒级），**全程不缓存流**。TTFT = 第一个 data chunk 到达时间 - 请求开始时间。
12. **Gateway 是否应重新序列化 chunk？** 你的倾向正确，**不应**。litellm 重序列化是因为多供应商协议归一化的刚需；代价是丢未知字段、浮点表示变化、chunk 边界改变可能破坏 `delta.tool_calls` 分片拼接。EMG 单后端透传即可完全规避此类 bug 面。

---

## 4. Tool Calling 调研结论

1. **Gateway 需要理解 Tool Calling 吗？** 不需要语义理解，只需要**不破坏**。请求侧把 `tools/tool_choice/parallel_tool_calls/response_format` 当作普通 JSON 字段透传；响应侧原样转发 `tool_calls/finish_reason`；流式侧原样转发 `delta.tool_calls`。
2. **request JSON 能否基本透明透传？** 能，且应该（详见 §5 dict 方案）。
3. **是否存在 Gateway 重写这些字段的情况？** 存在但都有特定动机：litellm 做 Anthropic↔OpenAI 协议转换时必然重写 tool_calls 结构；部分网关会给缺失的 `tool_call_id`/`index` 补默认值；new-api 有 param_override 功能允许管理员强制改参。EMG 单协议直通，**一律不改**。
4. **Streaming Tool Call 为什么最容易出问题？** 因为 OpenAI 规范下，一次 tool call 的 `arguments` 字符串被切成多个 delta chunk，客户端负责按 `index` 聚合并拼接 `function.arguments`，直到 `finish_reason=="tool_calls"`。任何中间层若：重排 chunk、丢弃 `index`/`id` 字段、重新编码转义、或合并 chunk 边界，都会让客户端拼出残缺 JSON。这就是"绝不重序列化"的根本原因。
5. **arguments 多 chunk 如何处理？** 这是**客户端（OpenCode）的职责**，网关不做任何拼接。
6. **是否完全不拼接 arguments 只转发？** 是。明确采纳。
7. **OpenCode Agent 场景还需注意的字段**：`stream_options.include_usage`（我们主动注入，注意别覆盖客户端已设值时产生两个 usage 块的边界情况——只在缺失时注入）；`finish_reason` 取值 `stop/length/tool_calls` 都要能透传；Qwen 思考模型的 `reasoning_content`（llama.cpp `--reasoning-format` 控制，透传即可）；`response_format: json_schema`；llama.cpp README 明确 `parallel_tool_calls` "仅部分模型支持"（透传，勿校验拦截）。

---

## 5. OpenAI-compatible Proxy 设计建议

1. **固定 Pydantic schema 还是 dict？** **dict + 最小验证**。理由：(a) OpenAI 字段持续增加（近期新增 `web_search_options`、`reasoning_effort`、`stream_options` 等），固定 schema 会静默丢弃新字段；(b) FastAPI 的 Pydantic 默认忽略额外字段，正是"新字段被吃掉"的典型事故来源；(c) new-api（Go struct + json.RawMessage）与 litellm（Pydantic 但 `extra="allow"`）殊途同归都在保护未知字段。EMG 做法：`body = await request.json()`，只校验 `model` 是字符串、提取 `stream` 布尔值、`messages` 存在性宽松检查，其余不动。
2. **如何避免 schema 丢字段**：dict 透传从根上消除该问题；唯一允许修改的字段是按需注入 `stream_options.include_usage`。
3. **Headers 规则**：
   - 删除（hop-by-hop 及代理职责）：`Connection`、`Keep-Alive`、`Transfer-Encoding`、`TE`、`Trailer`、`Upgrade`、`Proxy-*`
   - 替换：`Authorization`（换 upstream 凭据）、`Host`（由 httpx 按 base_url 重建）
   - 删除/重建：`Content-Length`（httpx 重算）
   - 建议删除：`Accept-Encoding`（避免 upstream 返回 gzip 使行解析复杂化）
   - 可透传：`User-Agent`、`Accept`、`X-Request-Id`、其他 `X-*` 自定义头
   - 绝不透传给 upstream：客户端的 `Authorization`（除非 upstream 需要，则替换）
4. **Key 替换**：backend 表存 upstream api_key（llama.cpp 若启用 `--api-key` 则填入，未启用则不带 Authorization 头）。
5. **HTTP 错误映射**：

   | 场景 | 返回 |
   |---|---|
   | upstream 返回 401/403/404/400/429/500 | **原样透传** status + body（llama.cpp 已是 OpenAI error envelope） |
   | EMG 鉴权失败 | 401 `{"error":{"message":"Invalid API key","type":"invalid_request_error","code":"invalid_api_key"}}` |
   | EMG key 过期/禁用/额度尽 | 401/403 同上格式，code 区分 `key_expired/key_disabled/quota_exceeded` |
   | RPM 超限 | 429 + `Retry-After` 头 + code `rate_limit_exceeded` |
   | upstream 连接拒绝 | 502 `{"error":{...,"type":"api_error","code":"connection_error"}}` |
   | upstream 超时 | 504 `code:"timeout"` |
   | upstream 连接中断（流中途）| 流已开始则只能断开；未开始则 502 |

---

## 6. API Key 安全设计

1. **SQLite 存完整 key？** 否（你的倾向正确）。反面实证：new-api `model/token.go` 中 `Key string gorm:"type:varchar(128);uniqueIndex"` ——明文入库，DB 泄露即全部 key 泄露。
2. **推荐设计**：`emg_` + 32 字节 CSPRNG（`secrets.token_urlsafe(32)`）→ 约 43 字符。DB 存：`key_prefix`（如 `emg_a1b2c3d4`，用于展示识别）+ `key_hash`（SHA-256 hex，UNIQUE INDEX）。验证流程：取 Bearer token → sha256 → `SELECT ... WHERE key_hash=?` 等值索引查询。
3. **hash 选择**：**SHA-256 足够且最优**。实证：litellm `hash_token()` 就是 `hashlib.sha256(token.encode()).hexdigest()`（proxy/utils.py:3552-3556，无盐）；GitHub PAT、GitLab 同模式。bcrypt/argon2 是为低熵人类口令设计的抗爆破慢哈希，对 ≥192bit 随机 key 毫无增益且每次请求引入 100ms 级延迟——明确不用。
4. **只展示一次**：合理，业界标准（GitHub/OpenAI/litellm 均如此），配合 prefix 识别。
5. **字段评估**：你列的 id/user_id/key_prefix/key_hash/enabled/expires_at/rpm_limit/token_limit/created_at/last_used_at 足够 v0.1。建议增补：`name`（备注名，便于 UI/CLI 管理）、`token_used`（冗余累计，免得额度判断每次 SUM 日志表；可用异步增量更新，litellm 正是这么做的）。`deleted_at` 软删留到 v0.2。
6. **快速 lookup**：key_hash 上的 UNIQUE 索引，O(log n)，微秒级。无需 salt（高熵输入不存在彩虹表攻击面）。
7. **salt？** 不需要（同上）。若想进一步防御"DB 泄露但代码/配置未泄露"，可升级为 HMAC-SHA256(secret_key, token)，secret 放配置文件——v0.1 可选项，非必需。
8. **日志防泄露**：日志/管理接口只输出掩码 `emg_abcd************wxyz`（new-api `MaskTokenKey` 同款思路）；异常堆栈与 access log 中 redact `Authorization` 头；错误信息不含 key 片段。

---

## 7. SQLite Schema 建议

五张表（users/api_keys/backends/request_logs/settings）评估：**合理，保留**。backends 表现在只有一行也是对的——它是未来多后端的落点，成本低。

`request_logs` 最终建议字段（在你候选基础上加 ★）：

```sql
CREATE TABLE request_logs (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id          TEXT NOT NULL,        -- uuid4
  user_id             INTEGER,
  api_key_id          INTEGER,
  backend_id          INTEGER,
  model               TEXT,
  endpoint            TEXT DEFAULT '/v1/chat/completions',  -- ★ 未来 embeddings/images
  started_at          INTEGER NOT NULL,     -- Unix UTC 秒
  finished_at         INTEGER,
  duration_ms         INTEGER,
  ttft_ms             INTEGER,              -- ★ 强烈建议（首个 chunk 到达）
  prompt_tokens       INTEGER,
  completion_tokens   INTEGER,
  total_tokens        INTEGER,
  stream              INTEGER,              -- 0/1
  finish_reason       TEXT,                 -- ★ stop/tool_calls/length/null
  status_code         INTEGER,              -- 给客户端的状态
  upstream_status_code INTEGER,             -- ★
  client_ip           TEXT,                 -- ★ nullable
  input_bytes         INTEGER,              -- ★ 便宜且有容量分析价值
  output_bytes        INTEGER,              -- ★
  error_type          TEXT,                 -- null=成功; timeout/upstream_error/
                                            -- client_disconnected/rate_limited...
  error_message       TEXT                  -- ★ 截断至 ~500 字符
);
```

逐问回答：
1. 缺的重要字段：上表 ★ 各项；其中 `ttft_ms`、`upstream_status_code`、`finish_reason`、`error_type` 四个价值最高。
2. **ttft_ms 应记录**：是。new-api 有专门 `SetFirstResponseTime()`；这是 LLM 网关最有价值的性能指标，采集成本为零。
3. **client_ip**：建议记录（nullable）。litellm/new-api 都支持 IP 白名单，说明该字段有真实用途；v0.1 仅记录不校验。
4. **input/output_bytes**：建议记录，两列整数而已。
5. **upstream_status_code**：建议记录（区分"网关错"与"上游错"必备）。
6. **finish_reason**：建议记录（Agent 场景 tool_calls 占比是重要运营指标）。
7. **prompt/response 内容默认不存**：你的倾向正确，同意。依据：litellm 的 spend_logs 也只存元数据不存内容；存内容的合规/体积负担远大于收益。将来加 `settings.debug_log_content` 开关即可，schema 无需预埋。

---

## 8. Usage Analytics / 时段统计设计

1. **v0.1 直接 GROUP BY？** 是。SQLite 在百万级行数、有索引时聚合查询为毫秒~几十毫秒级，远未到需要预聚合的规模。
2. **何时需要 hourly_usage/daily_usage 预聚合表？** 经验阈值：request_logs > 100 万行，或时段聚合 P95 > 200ms 时引入。届时用定时任务（每小时/每天）回填而非触发器（触发器会让每次写入变慢）。v0.1 不建。
3. **timestamp 存什么？** `INTEGER Unix epoch（UTC）`。比较整数快、无时区歧义、体积小。litellm 的 startTime、new-api 的 CreatedTime(bigint) 全是这个模式。
4. **时区处理（用户 UTC+8）**：存储永远 UTC；显示时转换。两种方式：SQL 层 `datetime(started_at,'unixepoch','+8 hours')`，或 Python 层 `datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))`。API 返回建议双字段：`bucket_start_utc` + `bucket_start_local`，前端随便用。**注意"天/周/月"分桶必须按本地时区切**（用户说"今天"指北京时间的一天），所以 GROUP BY 里就要带 `'+8 hours'` 修饰符。
5. **推荐 SQL 写法**：
```sql
-- 按小时
SELECT strftime('%Y-%m-%dT%H:00:00', started_at,'unixepoch','+8 hours') AS bucket,
       COUNT(*) AS requests, SUM(prompt_tokens), SUM(completion_tokens),
       SUM(total_tokens), AVG(duration_ms)
FROM request_logs
WHERE started_at >= :from AND started_at < :to
GROUP BY bucket ORDER BY bucket;
-- 按天：%Y-%m-%d；按月：%Y-%m
-- 按周（ISO 周，周一起始，UTC+8）：
strftime('%Y-%W', started_at,'unixepoch','+8 hours') -- %W 周一起始，够用
```
6. **索引**：
```sql
CREATE INDEX idx_rl_started ON request_logs(started_at);
CREATE INDEX idx_rl_key_time ON request_logs(api_key_id, started_at);
CREATE INDEX idx_rl_user_time ON request_logs(user_id, started_at);
CREATE INDEX idx_rl_model_time ON request_logs(model, started_at);
```
（覆盖主要过滤组合；SQLite 会自动用于 WHERE + GROUP BY。）
7. **INTEGER vs TEXT datetime**：选 INTEGER。TEXT ISO8601 可读性好但：体积大 ~30%、比较依赖格式一致、函数修饰慢。管理工具需要可读性时用视图或查询时转换。

---

## 9. Token Usage 统计方案

| 方案 | 可靠性 | 复杂度 | 性能影响 | 结论 |
|---|---|---|---|---|
| A. 记录 null | 低 | 零 | 零 | 仅作 fallback |
| B. 网关自己 tokenize | 高（近似） | 高（需 tokenizer/近似器，Qwen 词表） | 每次 CPU 开销 | **排除** |
| C. 注入 `stream_options.include_usage=true` + 解析末尾 usage 块 | **高（官方机制）** | 低（一个前缀检查+至多一次 json.loads） | ≈0 | **主方案** |
| D. llama.cpp /metrics 或日志 | 低（全局累计，难归属到请求） | 中 | 低 | 排除 |

事实依据（实测 llama.cpp 仓库）：PR #16052（2025-09-18 merge）"server : include usage statistics only when user request them"；此前 #15444 曾总是发送，被 issue #16048 按规范修正。**结论**：非流式读 `usage` 字段即可；流式注入 include_usage 并旁路解析 `choices:[]` 的 usage 块；拿不到记 NULL。完全满足"不为统计拖慢请求"。

---

## 10. 限流方案

1. **单实例内存 limiter？** 可以且应该。litellm 的 RPM/TPM 计数本质也在内存（Redis 只是为了多实例同步），EMG 单实例无此需求。
2. **算法**：**滑动窗口日志的简化版（deque 时间戳队列）或固定窗口**均可。推荐 fixed window（60s 窗口 + 计数器）：实现 10 行、RPM 精度要求下边界误差（最坏 2×瞬时）完全可接受；sliding window log 更精确但要存每个 key 的时间戳队列。token bucket/leaky bucket 是为平滑突发速率设计的，对 RPM 这种"每分钟 N 次"语义过度设计。并发限制不走限流算法，走 Semaphore（§11）。
3. **SQLite 只存配置**：正确。`api_keys.rpm_limit` 是配置；计数在内存 dict。litellm 同构（DB 存 limit 字段，计数在 cache）。
4. **重启窗口丢失可接受吗**：可接受。丢失方向是"清零放宽"，最坏后果是多放行一分钟流量，无害；为此持久化计数得不偿失。
5. **429 推荐格式**（OpenAI 风格）：
```json
{"error":{"message":"Rate limit reached for key emg_abcd****wxyz: 60 requests per minute. Please retry after 12 seconds.","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}
```
外加 HTTP 头 `Retry-After: 12`、`X-RateLimit-Limit-Minutes: 60`、`X-RateLimit-Remaining-Minutes: 0`。

---

## 11. 并发方案

1. **允许多人请求进入？** 是。uvicorn 异步架构天然支持任意并发进入，鉴权/排队不阻塞事件循环。
2. **upstream parallel=1 时在哪排队？** **在 Gateway 排队**，用 `asyncio.Semaphore(N)` 包裹 upstream 调用段。理由：llama-server 内部排队是无反馈的（客户端只见挂起连接，无法区分排队还是死锁），且占用 httpx 连接池槽位；Gateway 排队可实现：等待超时（如 120s 未获得槽位返回 429/503 + `Retry-After`）、公平 FIFO、以及排队指标观测。llama.cpp 本身也有 slot 排队与 `--timeout`（默认 3600s），两层并存不冲突。
3. **v0.1 需要 Semaphore 吗？** 需要，N 初值 = llama `--parallel` 值（当前 1），配置化。
4. **未来 parallel=4**：改一个配置值即可，代码零改动。
5. **自身最大并发**：设两层——upstream semaphore（上述）+ uvicorn `--limit-concurrency` 兜底（如 64，防止恶意连接堆积内存）。

---

## 12. Timeout / Client Disconnect（重点）

1. **httpx 默认超时不适合 LLM？** 完全不适合。官方文档确认：**默认 `Timeout(5.0)`，connect/read/write/pool 四维全是 5 秒**。LLM 首 token 经常 >5s，直连必炸。
2. **推荐配置**：
```python
httpx.Timeout(connect=5.0, write=60.0, read=None, pool=10.0)
```
3. **Streaming read=None？** 是，read 设 None（或极大值如 3600s），靠两个机制兜底：① 外层总 deadline（如单请求上限 30 分钟，配置化）；② 空闲检测可选（new-api 用 per-chunk reset 的 ticker 实现 idle timeout，v0.1 可不做）。write=60s 覆盖大 prompt 慢上传场景。
4. **客户端断开后取消 llama.cpp 推理**：机制已核实（Starlette responses.py 源码）：`StreamingResponse.__call__` 在 ASGI spec<2.4 时用 collapsing task group 同时跑 `stream_response` 和 `listen_for_disconnect`；uvicorn 在客户端 FIN 时投递 `http.disconnect`，task group 随即**取消你的 async generator**。你要做的：在 generator 的 `finally` / except `asyncio.CancelledError` 中执行 `await upstream_resp.aclose()` → httpx 关闭连接 → llama-server 写出失败即中止该 slot 推理。new-api 在 Go 侧做了完全等价的事（select Request.Context().Done() → resp.Body.Close()）。**注意事项**：日志写库放在被 shield 的独立 task 里，否则会被连带取消导致漏记。
5. **is_disconnected() 可靠吗？** `request.is_disconnected()` 是轮询式（non-blocking receive），适合手动检查点；对 SSE 转发场景，**StreamingResponse 的内建取消更可靠**（事件驱动、无轮询间隔）。uvicorn h11 下两者都工作正常。结论：用内建机制，不手写轮询。

---

## 13. FastAPI + httpx vs aiohttp

**明确推荐：FastAPI + httpx + uvicorn（方案 A）。**

| 维度 | FastAPI+httpx | aiohttp |
|---|---|---|
| SSE proxy | StreamingResponse 内建断连取消（§12 已核实源码） | web.StreamResponse 手写一切 |
| 请求校验 | dict 透传即可，Pydantic 只管 admin/config | 全手动 |
| SQLite | aiosqlite（asyncio 原生） | 也可用，无差异 |
| Admin API/WebUI 后续 | OpenAPI 文档自动生成、生态最大 | 手动维护路由/文档 |
| 测试 | TestClient 基于 httpx，ASGI 直测 | 需起真实端口或另搭 |
| 性能 | 本场景瓶颈在 GPU（秒级），框架差异 <1ms 无意义 | 略低开销 |

aiohttp 唯一优势是少一层依赖，但对"后续要做 Web Admin"的目标是净劣势。

---

## 14. Python 环境建议（老系统兼容）

1. **Python 版本**：**3.12.x**（conda-forge 构建 target glibc≥2.17，兼容老系统；3.12 wheel 生态最成熟稳定；3.13 可用但保守起见 3.12）。注意：你提供的 "Ubuntu 16.04 + glibc 2.31" 数据矛盾（16.04 是 glibc 2.23，2.31 属于 20.04）——但因为走 micromamba 独立环境，发行版差异基本无关紧要，仅需确认内核版本支持即可。
2. **当前最低版本要求**（逐一实测 pyproject.toml / PyPI）：

   | 包 | requires-python | License | 备注 |
   |---|---|---|---|
   | fastapi | ≥3.10 | MIT | 依赖 starlette≥0.46、pydantic≥2.9 |
   | uvicorn | ≥3.10 | BSD-3-Clause | h11 协议即可，不必装 [standard] |
   | httpx | ≥3.9 | BSD-3-Clause | 纯 Python |
   | aiosqlite | ≥3.9 | MIT | 纯 Python，单线程队列模型天然串行化写 |

   全部满足 3.12。
3. **固定版本？** 是。网关是长驻基础设施，升级必须受控。
4. **锁定策略**：`requirements.txt` 全部 `==` 精确 pin（约 8 个直接依赖 + 传递依赖冻结）；可选进阶用 pip-compile 生成带 hash 的 lock 文件；micromamba environment.yml 固定 `python=3.12`。升级流程：新 branch → 跑测试矩阵 → 合入。（本阶段只定策略，不执行安装。）

---

## 15. API / CLI 设计建议

Public 三端点（/health、/v1/models、/v1/chat/completions）合理。**明确推荐：v0.1 采用 CLI-only 管理，不开放任何 Admin HTTP API。**

- `python -m easymodelgate.cli user create/list/disable`
- `python -m easymodelgate.cli key create --user u1 --rpm 60 [--expires 2026-12-31]`（打印唯一一次完整 key）
- `python -m easymodelgate.cli key disable/revoke <prefix>`
- `python -m easymodelgate.cli usage summary --from --to --granularity day|hour|week|month [--user|--key|--model]`

理由：CLI 直接进程内访问 SQLite，无网络攻击面、无需设计 admin 鉴权体系（master key 管理、防暴力破解都是工作量）；你计划的 `GET /admin/usage/summary` 也建议 v0.1 先做成 CLI 子命令。Admin HTTP API 放 v0.2/v0.3 与 Web UI 一起做。CLI 与核心逻辑共用 service 层，未来加 HTTP 只是薄壳。

---

## 16. 测试矩阵（18 项）

测试基建：pytest + pytest-asyncio；mock upstream = 一个可编程的假 llama-server（FastAPI 小应用，能按剧本返回 SSE 序列/延迟/错误/半途断开）；用 httpx `ASGITransport` 直测 app 无需真实端口；客户端断连用 task cancel 或半关闭 socket 模拟；参考 new-api `stream_scanner_test.go`（16KB 的 SSE 边界用例集）的用例设计思路（AGPL，只学用例分类不抄码）。

| # | 用例 | 类型 |
|---|---|---|
| 1-4 | key 正确/错误/disabled/expired → 200/401/403/401 | 单元 |
| 5 | /v1/models 格式与过滤 | 单元 |
| 6-8 | non-stream / streaming / [DONE] 顺序与完整性 | 单元 |
| 9-10 | upstream 500 透传、upstream timeout→504 | 单元 |
| 11 | client disconnect → upstream 被 aclose（断言 mock 收到连接关闭） | 单元 |
| 12-13 | tool calling non-stream / streaming（多 chunk arguments 分片保真比对） | 单元 |
| 14 | usage logging（含注入 include_usage 后 usage 块解析） | 单元 |
| 15-17 | hour/day 聚合 SQL 正确性（含 UTC+8 边界）、RPM 429 + Retry-After | 单元 |
| 18 | SQLite restart persistence（tmp_path 重开库） | 单元 |
| 19 | 真实链路 OpenCode→EMG→llama.cpp→Qwen：对话/流式/tool call/长 Agent 任务 | 集成脚本 |

---

## 17. 性能目标（v0.1）

| 指标 | 目标 |
|---|---|
| 额外 TTFT 开销 | **目标 <10ms，上限 <20ms**（行透传实际可达 1-5ms） |
| 非流式额外延迟 | <20ms |
| 内存 | <150MB RSS（FastAPI+uvicorn 进程基线典型 60-120MB） |
| CPU | 空闲 ≈0%；转发期单核占用极低（瓶颈永远在 GPU） |
| SQLite | **WAL=on、busy_timeout=5000ms、synchronous=NORMAL**；写入经 aiosqlite 单连接自然串行化，日志插入用后台 task 异步批量（借鉴 litellm 队列批写思想，简化为每 N 条或每秒 flush） |

---

## 18. v0.1 推荐架构图

```
                ┌────────────────────────────────────────────┐
 OpenCode/API ──► uvicorn :3000                               │
                │  FastAPI app                                │
                │   ├─ middleware: auth(key_hash lookup)      │
                │   ├─ middleware: RPM limiter (in-memory)    │
                │   ├─ POST /v1/chat/completions              │
                │   │    ├─ dict body (最小校验)               │
                │   │    ├─ Semaphore(upstream_slots) 排队     │
                │   │    ├─ 注入 stream_options.include_usage  │
                │   │    ├─ httpx.AsyncClient.stream()         │
                │   │    ├─ 非200 → 透传错误                    │
                │   │    └─ StreamingResponse ◄─ 行透传循环     │
                │   │         ├─ 旁路: TTFT/[DONE]/usage 嗅探  │
                │   │         └─ finally: aclose() ← 断连取消   │
                │   ├─ GET /health, GET /v1/models            │
                │   └─ asyncio task: 日志异步批量写             │
                │  aiosqlite ──► emg.db (WAL)                 │
                └──────────────┬─────────────────────────────┘
                               ▼
                     llama.cpp :8080 (--parallel 1)
                               ▼
                         Qwen 27B (GPU)
```

## 19. 推荐目录结构

```
easymodelgate/
├── pyproject.toml / requirements.txt / requirements.lock
├── environment.yml            # micromamba env 定义
├── easymodelgate/
│   ├── __init__.py
│   ├── __main__.py            # python -m easymodelgate serve
│   ├── cli.py                 # user/key/usage 子命令
│   ├── config.py              # env/toml 配置加载
│   ├── app.py                 # FastAPI 组装
│   ├── routers/
│   │   ├── public.py          # health/models/chat/completions
│   │   └── (admin.py — v0.2 预留空位)
│   ├── core/
│   │   ├── auth.py            # key 校验依赖
│   │   ├── ratelimit.py
│   │   ├── errors.py          # OpenAI error envelope
│   │   └── security.py        # 生成/hash/掩码 key
│   ├── proxy/
│   │   ├── upstream.py        # httpx client 管理、header 处理
│   │   └── sse.py             # 行透传生成器 + 旁路嗅探
│   ├── services/
│   │   ├── usage_log.py       # 异步批量写
│   │   └── analytics.py       # 聚合查询(SQL)
│   └── db/
│       ├── database.py        # aiosqlite + PRAGMA
│       ├── schema.sql
│       └── dao.py
├── tests/
│   ├── conftest.py            # fake llama upstream fixture
│   ├── unit/...
│   └── integration/test_real_chain.py
└── scripts/integration_test.py
```

## 20. 推荐数据库表结构

（users/api_keys/backends/settings 常规；关键表 DDL 见 §7 request_logs；要点汇总）

```sql
PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA synchronous=NORMAL;

users(id PK, username UNIQUE, enabled, created_at, note)
api_keys(id PK, user_id FK, name, key_prefix, key_hash UNIQUE, enabled,
         expires_at NULL, rpm_limit NULL, token_limit NULL, token_used DEFAULT 0,
         created_at, last_used_at)
backends(id PK, name UNIQUE, type 'llamacpp', base_url, api_key NULL,
         model_map_json NULL, capabilities_json NULL, enabled, created_at)
request_logs(…见 §7…)
settings(key PK, value_json)
-- 索引见 §8.6
```

## 21. v0.1 明确功能清单

GET /health；GET /v1/models；POST /v1/chat/completions（dict 透传+SSE+Tool Calling 保真）；Bearer 鉴权（emg_ key、SHA-256 存储、show-once、禁用/过期/RPM/Token 额度/last_used_at）；usage 记录（tokens/TTFT/duration/bytes/status/error_type，异步批量写）；时段统计（CLI 查询，UTC 存储/UTC+8 展示，hour/day/week/month/custom × user/key/model 过滤）；内存 RPM 限流 + 429 envelope；upstream Semaphore 并发控制；断连取消 upstream；SQLite WAL 持久化；管理 CLI。

## 22. v0.1 明确非目标

Web Admin、Admin HTTP API、PostgreSQL、Redis、OAuth、RBAC、商业计费、云端聚合、ComfyUI/图像/语音、Embeddings 路由、多机集群、GPU 调度、TPM/concurrent 限制（预留字段与接口但不实现）、prompt 内容存储、预聚合表。

## 23. v0.2 / v0.3 演进建议

- **v0.2**：Admin HTTP API（master key 保护）+ 简易 Web Dashboard（复用 analytics service）；TPM 与并发限制；多 backend（vLLM/Ollama/SGLang——均为 OpenAI 兼容，Backend interface 已天然容纳）；HMAC key hash 可选。
- **v0.3**：Embeddings/completions 端点、简单 fallback/健康检查（学 Portkey）、审计日志、key 软删与轮换。
- **抽象原则（现在做）**：`backends.type` 字段 + BackendConfig 数据类 + "取 upstream client"的单一函数入口——这三样够未来扩展；**不做**通用 Backend protocol 多态体系和 capability 协商框架。ComfyUI 属于"异步任务+WebSocket+文件"范式，与 streaming proxy 完全异构，将来应为独立 handler 家族（new-api 也是 relay_task.go 独立处理任务型 API），**不要**为它在 v0.1 预埋任何东西——只要 endpoint/route 字段和 type 字段在，就没锁死。

## 24. 主要技术风险 Top 10

1. **客户端断连传播失效**（生成器未被取消/upstream 未关）→ GPU 空算。缓解：专项测试 #11；finally 清理。
2. **include_usage 注入副作用**：客户端已自带该参数时的重复/冲突；旧版 llama.cpp 行为差异（#15444 曾总发送）。缓解：仅缺失时注入 + 版本探测测试。
3. **SQLite 写锁竞争**：突发并发下 `database is locked`。缓解：WAL+busy_timeout+单写者+批量。
4. **日志写库阻塞事件循环**：同步写混入 async。缓解：aiosqlite + 后台队列。
5. **流中途 upstream 死亡的 UX**：客户端收到不完整流且无 [DONE]。缓解：文档说明 + error_type 记录 + （可选）发送 SSE error event。
6. **时区/分桶 off-by-one**："今天"边界错误。缓解：聚合 SQL 专项测试含 UTC+8 午夜边界。
7. **RPM 重启窗口丢失**引发误解。缓解：文档声明 + 可选启动告警。
8. **AGPL 污染**：误复制 new-api/croit 代码。缓解：纪律——只读行为与结构，实现全部自写。
9. **老系统环境漂移**：conda/micromamba 在 Ubuntu16.04 内核过旧的潜在符号问题。缓解：开发期先在该机冒烟验证 micromamba 安装（属实施阶段第一步）。
10. **范围蔓延**（向 litellm 功能面漂移）。缓解：§21/§22 清单即为契约。

## 25. 最终建议

**适合立即开始开发。** 所有高风险问题（SSE 保真转发、usage 获取、断连取消、key 安全、聚合查询）均已找到经同类项目验证的确定解，且互相兼容。技术栈无悬念，工作量集中在约 1500-2500 行的自有代码。建议按 schema.sql → auth → proxy 透传 → SSE → usage/日志 → 限流 → CLI → 测试矩阵的顺序推进。

---

## Review Decision

**Phase 0: PASS**

审核结论：

- 当前技术路线具备进入下一阶段的条件。
- 无需继续进行大规模同类项目调研。
- 下一阶段为 Phase 0.5：
  - llama.cpp Streaming Usage 实测
  - httpx SSE iterator 实测
  - Tool Calling Streaming 实测
  - Client Disconnect 传播实测
  - Python/FastAPI 环境兼容性实测

注意：

Phase 0.5 如果发现与本报告结论不同的实际行为，
应在 Phase 0.5 报告中记录差异，
不要修改本 Phase 0 历史报告。
