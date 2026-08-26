# EasyModelGate v0.1 最终开发规格

- Project: EasyModelGate
- Version: v0.1
- Status: Frozen
- Date: 2026-08-26
- Phase 0: PASS
- Phase 0.5: PASS
- Language: 中文
- Purpose: EasyModelGate v0.1 正式开发与验收依据

> 本文件为 EasyModelGate v0.1 的冻结规格。
>
> 开发过程中如发现必须修改架构的阻塞性问题：
>
> 不得直接悄悄修改本文件。
>
> 应：
>
> 1. 暂停对应阶段
> 2. 记录问题
> 3. 提出变更建议
> 4. 等审核后再修改规格

---

## 一、重要要求：项目文档统一使用中文

从本阶段开始：

所有面向项目人员阅读的正式文档统一使用中文撰写。

包括但不限于：

README.md、开发任务书、设计说明、架构说明、数据库说明、测试报告、阶段报告、部署说明、使用说明、故障排查文档、ADR / Architecture Decision Record。

要求：

- 文件名可以继续使用英文
- 代码变量、类名、函数名使用英文
- API 字段名使用英文
- SQL 字段名使用英文
- 命令行参数使用英文
- 技术名词必要时保留英文
- 但正文说明统一使用中文

已有 Phase 0 / Phase 0.5 历史报告保持原样，不要为了统一中文而回改历史报告。

## 二、项目根目录

项目根目录：

`<PROJECT_ROOT>`

已有 README.md 与 docs/（research / specifications / protocol / decisions）、experiments/phase-0.5/。不得删除或覆盖已有 Phase 0 / Phase 0.5 历史资料。

## 三、首先保存本最终任务书

将本任务完整保存为 `docs/specifications/EasyModelGate-v0.1-Final-Specification.md`，文件顶部增加元信息（Project / Version / Status: Frozen / Date / Phase 状态 / Language / Purpose），并注明本文件为冻结规格及上述变更控制流程。（已按此执行。）

## 四、Phase 0 / Phase 0.5 状态

Phase 0：PASS；Phase 0.5：PASS。

已验证事实（v0.1 实现必须遵守）：

1. llama.cpp Streaming Usage：默认 stream=true 无 usage；include_usage=true → usage chunk 出现在 [DONE] 前；include_usage=false → 无 usage。当前 build 额外提供 `prompt_tokens_details.cached_tokens`，因此 v0.1 必须记录 cached_tokens。
2. SSE Iterator：TCP/HTTP chunk ≠ SSE event；一个 HTTP chunk 可能包含多个 SSE events。最终方案：`resp.aiter_bytes()` + 原始 bytes 直接转发 + 只读 incremental SSE scanner。
3. Tool Calling：function.arguments 实测分为多个 chunk。Gateway 不得拼接、不得重排、不得重新序列化；delta.tool_calls 必须完整透明转发。
4. Client Disconnect：Client disconnect → Gateway cancellation → upstream aclose → fake upstream stop，本地传播约 2ms。正式实现必须采用这一模式。
5. Python Environment：Python 3.12.13，micromamba 独立环境；FastAPI/httpx/uvicorn/aiosqlite/SQLite WAL 已验证正常。

## 五、v0.1 总体目标

当前：OpenCode → llama.cpp :8080 → Qwen3.8-27B。

目标：

```
OpenCode / OpenAI-compatible Client
                 ↓
          EasyModelGate :3000
                 ↓
       API Key / 限流 / 排队
                 ↓
       Usage / 日志 / Analytics
                 ↓
          llama.cpp :8080
                 ↓
             Qwen3.8
```

核心原则："透明代理优先。"

EasyModelGate 不负责：理解模型内容、修改模型回答、修改 Tool Calling、修复模型 JSON、重新组织 SSE、替客户端拼接 tool arguments。

EasyModelGate 负责：鉴权、安全、限流、排队、上游访问、透明转发、请求日志、Token Usage、性能指标、时段统计。

## 六、v0.1 Public API

正式实现：GET /health、GET /v1/models、POST /v1/chat/completions。

暂不实现：/v1/responses、/v1/embeddings、/v1/images、/v1/audio、ComfyUI API、Admin HTTP API。

## 七、技术栈

正式环境 Python 3.12.13，环境管理 micromamba。开发环境名称建议 easymodelgate-dev，生产环境名称建议 easymodelgate。禁止使用 system Python、禁止使用 base conda 环境。

依赖版本冻结：

```
fastapi==0.141.1
starlette==1.6.0
httpx==0.28.1
uvicorn==0.52.4
aiosqlite==0.22.1
pydantic==2.13.4
pytest==9.1.1
pytest-asyncio==1.4.0
```

Python 优先固定 3.12.13；如环境管理器无法精确固定 patch，至少固定 python=3.12 并记录实际解析出的版本。

## 八、正式项目结构

```
EasyModelGate/
├── README.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── environment.yml
├── configs/
│   └── config.example.toml
├── data/
├── logs/
├── docs/
│   ├── research/
│   ├── specifications/
│   ├── protocol/
│   ├── decisions/
│   ├── development/
│   └── deployment/
├── experiments/
│   └── phase-0.5/
├── easymodelgate/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py
│   ├── cli.py
│   ├── config.py
│   ├── routers/
│   │   └── public.py
│   ├── core/
│   │   ├── auth.py
│   │   ├── security.py
│   │   ├── errors.py
│   │   ├── ratelimit.py
│   │   └── concurrency.py
│   ├── proxy/
│   │   ├── upstream.py
│   │   ├── headers.py
│   │   └── sse.py
│   ├── services/
│   │   ├── request_logging.py
│   │   ├── usage.py
│   │   └── analytics.py
│   └── db/
│       ├── database.py
│       ├── schema.sql
│       └── dao.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fake_upstream/
└── scripts/
```

不要为了"看起来专业"增加无实际用途的层级。

## 九、配置系统

TOML + 环境变量覆盖。configs/config.example.toml 至少包括：

server.host / server.port；database.path；upstream.base_url / upstream.api_key_file / upstream.slots；timeouts.connect / write / read / pool / total_request；security.key_prefix；usage.timezone；limits.max_client_concurrency。

正式敏感配置不得写入 config.example.toml。

## 十、Upstream Key

llama.cpp API Key 不得存进 SQLite；不得硬编码在源码 / 写进 README / 写进 Git / 写进实验报告 / 写进普通日志。

采用 API Key 文件（如 configs/upstream_key，生产 chmod 600）或环境变量 EMG_UPSTREAM_API_KEY。优先级：环境变量 > secret file > 其他。不允许明文 secret 出现在公开配置模板。

## 十一、OpenAI-compatible Request

不得建立过于严格的 ChatCompletion Pydantic 请求模型。使用 `body = await request.json()`，只做最低限度验证：body 是 object；model 如存在必须是 string；messages 存在且结构基本有效；stream 读取为 bool。其它所有未知字段保留（tools、tool_choice、parallel_tool_calls、response_format、reasoning_content、reasoning_effort、stream_options、temperature、top_p、max_tokens、stop、seed 等）。未来新字段不得因 schema 未升级被静默丢弃。

## 十二、Streaming Usage 注入规则

如果 stream == true 且客户端完全没有提供 stream_options，则 Gateway 注入 `{"stream_options":{"include_usage":true}}`。客户端已提供 stream_options 则不覆盖（尤其 include_usage=false 必须尊重）；已有 stream_options 但无 include_usage 时 v0.1 默认不修改该 object。保守策略：只有 stream_options 整体缺失时才自动注入。"缺字段则补 true"留待规格变更。

## 十三、Streaming Relay

使用 `httpx Response.aiter_bytes()`：

```python
async for chunk in upstream_response.aiter_bytes():
    scanner.feed(chunk)
    yield chunk
```

客户端收到的 chunk 必须是 upstream chunk 原始 bytes。禁止 json.loads→修改→json.dumps→yield 新 JSON；禁止 aiter_lines() 作为正式 relay transport（会移除原始行终止符，强制 Gateway 重建 SSE）。

## 十四、Incremental SSE Scanner

scanner 只用于旁路观测，不得修改 transport bytes。内部维护 carry buffer，每次 scanner.feed(chunk) 将 carry+chunk 按完整 SSE event 分割，分隔至少支持 `\n\n`（如成本低可兼容 `\r\n\r\n`）。未完整 event 保留在 carry buffer 等待下一 chunk。

Scanner 负责：识别第一个有效 data event；记录 TTFT；检测 [DONE]；检测 usage event；提取 usage；可提取 finish_reason。

Scanner 不负责：拼接 Tool Calling arguments、修改 SSE、重排 events、重构 events。

## 十五、Streaming Usage 解析

当前 llama.cpp usage chunk：choices == []，包含 usage.prompt_tokens / completion_tokens / total_tokens 以及 usage.prompt_tokens_details.cached_tokens。request log 必须支持 prompt_tokens / completion_tokens / total_tokens / cached_tokens。scanner 先检测包含 b'"usage"' 再进行一次 json.loads；不对普通 content chunk 每次完整 json.loads。Usage chunk 继续原样发送给客户端，不得 strip。

## 十六、cached_tokens

新增 cached_tokens INTEGER：记录 llama.cpp KV cache 命中对应的 prompt token 数。Analytics v0.1 支持累计 cached_tokens；不做复杂 cache hit ratio（除非实现非常简单）。未来可根据 cached_tokens / prompt_tokens 分析缓存效果。

## 十七、Tool Calling

实测 function.arguments 跨多个 SSE event 分片；第一片可能带 id/type/name/index/arguments，后续只带 index/arguments fragment。

EasyModelGate 不得：拼接 arguments、验证 arguments JSON、修复 arguments、缓存整组 Tool Call、重排 events、改写 index、补 id、补 name。全部由 OpenCode / 客户端负责。正式定义：Tool Calling = Transparent Passthrough。

## 十八、Response Headers

Streaming：Content-Type: text/event-stream；建议 Cache-Control: no-cache、X-Accel-Buffering: no。不要主动写 Connection: keep-alive（HTTP/1.1 自行处理）。

## 十九、Request Headers

不能把客户端 Authorization: Bearer emg_xxx 转给 llama.cpp，必须替换为 upstream Bearer key。删除：Connection、Keep-Alive、Proxy-Authenticate、Proxy-Authorization、TE、Trailer、Transfer-Encoding、Upgrade、Host、Content-Length。建议不向 upstream 发送 Accept-Encoding（确保 aiter_bytes() 无压缩/解压差异）。可保留合理 Accept、User-Agent、X-Request-ID 以及安全的 X-* header。

## 二十、API Key 设计

客户端 Key 形如 emg_<random>，生成用 secrets.token_urlsafe(32)。完整 Key 仅创建时展示一次。SQLite 不保存完整 Key，保存 key_prefix 与 key_hash（key_prefix 示例 emg_a1b2c3d4；key_hash = SHA-256(full_key)，UNIQUE INDEX）。验证流程：Authorization Bearer token → SHA-256 → 数据库等值查询。

## 二十一、日志脱敏

任何日志禁止输出：Authorization、完整 emg_ key、完整 upstream key、完整用户 prompt、完整模型 response、完整 reasoning、完整 tool arguments。API Key 日志展示格式：emg_abcd****wxyz。错误日志不得包含完整 request body。

## 二十二、SQLite

正式数据库 data/easymodelgate.db。启动 PRAGMA：journal_mode=WAL、busy_timeout=5000、synchronous=NORMAL。schema 版本从 schema_version = 1 开始。

## 二十三、users 表

id、username UNIQUE NOT NULL、display_name、enabled、created_at、note。

## 二十四、api_keys 表

id、user_id、name、key_prefix、key_hash UNIQUE、enabled、expires_at、rpm_limit、token_limit、token_used、created_at、last_used_at。外键 user_id → users.id。

## 二十五、backends 表

保留 backend 抽象：id、name、type、base_url、api_key_ref、enabled、created_at。v0.1 type 取 openai-compatible 或 llamacpp 二选一并记录设计说明。推荐 type = llamacpp（便于未来区分 vllm/ollama/sglang/comfyui）。不要在数据库里存 upstream API Key。

## 二十六、request_logs 表

必须包含：id、request_id、user_id、api_key_id、backend_id、model、endpoint、started_at、finished_at、duration_ms、queue_wait_ms、upstream_duration_ms、ttft_ms、prompt_tokens、completion_tokens、total_tokens、cached_tokens、stream、finish_reason、status_code、upstream_status_code、client_ip、input_bytes、output_bytes、error_type、error_message（限长 ≤500 字符）。

## 二十七、禁止保存内容

request_logs 默认不保存 messages/prompt/assistant response/reasoning_content/tool arguments/tool results/System Prompt/用户文件内容。这是 v0.1 强制隐私原则。

## 二十八、时间

数据库时间 Unix epoch UTC。推荐 started_at / finished_at 使用 Unix milliseconds；若选择秒则全表与代码统一秒，不得混用。正式实现前在 schema 设计说明中明确一次。

## 二十九、时区

配置 usage.timezone（默认 Asia/Shanghai）。数据库永远 UTC；Analytics 转换至配置时区后分桶。不在 SQL 源码硬编码 "+8 hours"；以后允许 Asia/Tokyo、America/New_York 等。

## 三十、queue_wait_ms

当前 llama.cpp parallel = 1，Gateway 使用 asyncio.Semaphore(upstream.slots)。请求流：received → waiting semaphore → acquired → call upstream。记录 queue_wait_ms，用于区分"响应慢是 GPU 推理慢还是排队慢"。

## 三十一、upstream_duration_ms

记录获得 slot 后直到上游请求结束/断开的时间，用于区分 queue_wait 与真正 upstream service time。

## 三十二、TTFT

记录 ttft_ms：请求进入 EasyModelGate 到收到第一个真正模型 data chunk 之间的时间。不要把纯 SSE ping/comment 当作模型首 token；只把有效 data event 作为 TTFT 起点。

## 三十三、Concurrency

配置 upstream.slots = 1（对应当前 --parallel 1），使用 asyncio.Semaphore。未来 parallel=4 只需改配置 upstream.slots=4，尽量不改业务代码。

## 三十四、Client Concurrency

Gateway 允许多个客户端连接，但设置合理的 limits.max_client_concurrency 避免大量连接耗尽内存（可通过 uvicorn limit-concurrency 或应用层实现）。不过度复杂化。

## 三十五、Client Disconnect

使用 Phase 0.5 已验证模式：

```python
try:
    async for chunk in upstream.aiter_bytes():
        ...
        yield chunk
except asyncio.CancelledError:
    ...
    raise
finally:
    await upstream_response.aclose()
```

必须保证：客户端断开 → 上游连接关闭 → llama.cpp 尽快停止生成。

## 三十六、Request Log Detached Task

streaming finally 中创建独立 task（loop.create_task(persist_request_log(...))）。必须增加应用级 task registry（set[asyncio.Task]）：防止 task 被 GC，并方便 shutdown 时等待未完成日志任务。推荐模式：

```python
task = loop.create_task(...)
background_tasks.add(task)
task.add_done_callback(background_tasks.discard)
```

服务 shutdown 给日志任务合理时间 flush。不引入 Redis/RabbitMQ/Kafka。

## 三十七、Timeout

HTTPX 不得使用默认 timeout。冻结：connect = 5s、write = 60s、read = None、pool = 10s。另设 total_request_timeout 默认 1800 秒（30 分钟），必须配置化。

## 三十八、Non-streaming

stream=false 时正常等待 upstream JSON response，透传 body，同时旁路读取 usage 与 finish_reason（timings 可不入库）。记录 prompt_tokens / completion_tokens / total_tokens / cached_tokens / finish_reason。

## 三十九、Error Handling

统一 OpenAI-compatible error envelope：

| 场景 | 状态 | code |
|---|---|---|
| Key 缺失/无效 | 401 | invalid_api_key |
| Key disabled / expired | 401 | 相应 code |
| 权限问题 | 403 | - |
| RPM limit | 429 | rate_limit_exceeded |
| Token quota | 429 | insufficient_quota |
| upstream connect fail | 502 | connection_error |
| upstream timeout | 504 | timeout |

## 四十、Upstream Error

llama.cpp 返回 400/401/404/429/500 且 body 为合理 OpenAI-compatible error 时，尽量原 status + 原 body 返回客户端；同时记录 status_code、upstream_status_code、error_type。

## 四十一、RPM Limit

v0.1 内存实现，fixed window，按 api_key_id 统计每 60 秒请求数。SQLite 只存 rpm_limit 配置，不存实时 counter。重启后计数清零（接受）。429 返回 Retry-After。

## 四十二、Token Soft Quota

token_limit 为软额度：请求进入前 token_used >= token_limit 则拒绝；完成后 token_used += total_tokens。允许单次小幅超过后拒绝新请求。不实现 token reservation，不在请求前预估 max_tokens。

## 四十三、Usage Analytics

统计指标：requests、prompt_tokens、completion_tokens、total_tokens、cached_tokens、duration_ms、queue_wait_ms、upstream_duration_ms、ttft_ms。粒度：hour/day/week/month/custom。

## 四十四、Analytics Filters

支持 user / api_key / model / time range（今天、昨天、最近24小时、最近7天、本周、本月、自定义 from/to）。

## 四十五、Analytics 实现

v0.1 直接基于 request_logs SQL GROUP BY，不建 hourly_usage/daily_usage 预聚合表。仅当行数 ≥100 万或聚合 P95 >200ms 再考虑预聚合。

## 四十六、索引

至少：request_logs(started_at)、(user_id, started_at)、(api_key_id, started_at)、(model, started_at)；api_keys(key_hash UNIQUE)；users(username UNIQUE)。其它索引按实际 query plan 决定。

## 四十七、CLI

v0.1 管理功能以 CLI 为主，不做 Admin HTTP API。至少：

```
python -m easymodelgate user create
python -m easymodelgate user list
python -m easymodelgate user disable
python -m easymodelgate key create
python -m easymodelgate key list
python -m easymodelgate key disable
python -m easymodelgate usage summary
```

## 四十八、Key CLI

示例：

```
python -m easymodelgate key create --user alice --name laptop --rpm 60 --token-limit 10000000
```

完整 Key 仅 stdout 显示一次，并明确提示："请立即保存，该 Key 后续无法再次查看。"

## 四十九、Usage CLI

```
python -m easymodelgate usage summary --period today
python -m easymodelgate usage summary --period 7d --group-by day
python -m easymodelgate usage summary --from "2026-08-01 00:00" --to "2026-08-26 00:00" --group-by hour
```

支持 --user / --key / --model。输出中文表头优先。

## 五十、/health

GET /health 至少返回 {"status":"ok"}。建议增加 version、upstream_reachable，但不要每次调用 llama.cpp 做生成。可轻量 upstream check 或分 /health 与未来 /ready。v0.1 优先简单。

## 五十一、/v1/models

客户端必须 Bearer emg_ key 鉴权。Gateway 请求 llama.cpp /v1/models（替换 Authorization），不暴露 upstream secret。

## 五十二、版本

正式版本 0.1.0；代码中 `__version__ = "0.1.0"`。

## 五十三、LICENSE

自有代码推荐 Apache License 2.0（宽松、允许商用与闭源二次使用、含明确专利授权）。创建 LICENSE 文件。不复制 AGPL 项目代码（New API、croit/llm-gateway 为 AGPL，仅允许学习行为与设计思想）。

## 五十四、Protocol Samples 归档

Phase 0.5 REPORT 附录样本已审核通过。将有长期价值的脱敏样本复制到 docs/protocol/llamacpp/：stream-without-stream-options.sse、stream-include-usage-true.sse、stream-include-usage-false.sse、non-stream-response.json、tool-call-nonstream.json、tool-call-stream.sse、plain-lines-obs.json、toolcall-lines-obs.json、disconnect_metrics.json。

同时创建 docs/protocol/llamacpp/README.md（中文：样本来源、采集日期、llama.cpp 当前 build、用途、安全脱敏情况）。不删除 experiments 下原始文件。

## 五十五、README 更新

正式开发开始后更新 README.md，正文中文，至少包括：项目简介、当前状态、架构、快速启动、配置、API、CLI、安全原则、开发状态、文档索引。不承诺尚未实现的功能为"已支持"；用"已实现 / 开发中 / 计划"明确区分。

## 五十六~六十七、测试策略（摘要）

框架 pytest + pytest-asyncio；建立 fake upstream（SSE/超时/错误/工具调用/断连/usage 可编程），自动测试不依赖真实 GPU。

必测项编号清单（规格原文）：

- Auth（57 项内 #1-#7）：正确 Key、Key 缺失、错误 Key、disabled、expired、hash 查询、日志无泄漏
- Proxy（#8-#17）：/health、/v1/models、non-stream chat、streaming chat、[DONE]、upstream 400/429/500/timeout/connect fail
- SSE（#18-#24）：一 chunk 多 event、一 event 拆两 chunk（人工构造）、carry buffer 拼接、CRLF/LF、usage chunk、[DONE]、不重序列化（断言 client bytes == fake upstream bytes）
- Tool Calling（#25-#31）：non-stream tool_calls、streaming delta.tool_calls、arguments 分片、id 仅第一片、name 仅第一片、index 每片存在、finish_reason=tool_calls，输出 bytes 与 upstream 一致
- Usage（#32-#39）：non-stream usage、注入 usage、include_usage=false NULL、四类 token 数、持久化
- Disconnect（#40-#44）：client disconnect、upstream aclose、fake cancelled、detached log 完成、error_type=client_disconnected
- Concurrency（#45-#48）：slots=1 第二请求排队且 queue_wait_ms>0、semaphore 释放、upstream error 后不泄漏、disconnect 后不泄漏
- Rate Limit（#49-#52）：RPM 正常、超限 429、Retry-After、不同 Key 隔离
- Token Quota（#53-#56）：未达限额正常、达到 429 insufficient_quota、完成后增加、soft overrun
- Analytics（#57-#67 内）：hour/day/week/month/custom、user/key/model 过滤、UTC→Asia/Shanghai 午夜边界、cached_tokens 聚合、queue_wait 聚合
- SQLite（#68-#73）：WAL 开启、restart persistence、busy_timeout、并发写入、库不存在自动初始化、已存在不重复建表破坏数据

## 六十八、真实集成测试

自动测试通过后再测真实链路 OpenCode → EasyModelGate → llama.cpp → Qwen。

## 六十九、真实 OpenCode 测试

至少：A 普通问答；B Streaming；C Tool Calling（如只读 ls）；D 工具结果回传；E WebFetch Agent；F 多轮 Agent；G 接近真实 32K 工作流。验证不出现 ContextOverflow 之外的 Gateway 自身错误；不破坏 tools/tool_calls/finish_reason/reasoning content。

## 七十、真实断连测试

fake upstream 通过后，对真实 llama.cpp 做一次安全 spot check：较长 streaming 请求 + 客户端主动断开，确认 slot 尽快释放。只做一次，不反复浪费 GPU。

## 七十一、性能目标

额外 TTFT 目标 <10ms、上限 <20ms；非流式额外延迟 <20ms；空闲 CPU ≈0；RSS <150MB；Streaming 禁止完整缓存 response。

## 七十二、v0.1 明确不做

Web Admin、Admin HTTP API、PostgreSQL、Redis、OAuth、RBAC、商业计费、复杂余额系统、OpenRouter 聚合、OpenAI 云 API 聚合、TPM 精确限流、Token reservation、Redis distributed rate limit、多机负载均衡、GPU Scheduler、ComfyUI、Images、Audio、Embeddings、Responses API、自动 fallback、模型自动下载、模型启动管理、Docker 强依赖。

## 七十三、未来扩展原则

v0.1 只预留轻量接口：Backend type、Backend config、endpoint、upstream client factory。不创建巨大抽象体系。

v0.2：Web Dashboard、Admin API、TPM、Concurrent limit、多 OpenAI-compatible backend。
v0.3：Embeddings、Fallback、审计功能、Key rotation。
后续：ComfyUI/Image/Audio 异步任务（独立 handler family，不强行套进 chat proxy）。

## 七十四、开发阶段顺序

```
Phase 1  项目骨架 + 环境 + 文档 + Schema
Phase 2  Security + User/Key CLI
Phase 3  /health + /v1/models
Phase 4  Non-stream Chat Proxy
Phase 5  Streaming + SSE Scanner
Phase 6  Disconnect + Request Logging
Phase 7  Tool Calling 保真测试
Phase 8  Semaphore + Queue Metrics
Phase 9  Usage + cached_tokens + TTFT
Phase 10 Analytics
Phase 11 RPM + Soft Token Quota
Phase 12 完整自动测试
Phase 13 真实 OpenCode 集成测试
Phase 14 systemd 部署
```

## 七十五、阶段性暂停规则

Checkpoint 1：Phase 1-3 完成 → 报告项目结构、环境、Schema、Auth、Key CLI、health/models。
Checkpoint 2：Phase 4-7 完成 → non-stream/stream/scanner/disconnect/tool calling。
Checkpoint 3：Phase 8-11 完成 → queue/usage/cached_tokens/analytics/RPM/quota。
Checkpoint 4：自动测试全部通过。
Checkpoint 5：真实 OpenCode 全链路通过。
然后才 systemd。

## 七十六、安全边界

开发期间禁止：升级 Ubuntu/glibc、修改内核/NVIDIA Driver/CUDA、重新编译 llama.cpp、修改 Qwen GGUF、修改 GPU 分配、修改 llama.cpp context、修改 llama-server systemd、停止当前 llama-server、修改现有 OpenCode 主配置（除非集成测试步骤且可恢复地指向 EasyModelGate）。任何系统层修改先暂停报告。

## 七十七、OpenCode 配置测试原则

集成测试阶段不直接覆盖现有工作配置；优先备份或创建专门测试 provider（如 local-qwen-direct 与 local-qwen-emg 并行），支持 A/B 行为对比。正式配置变更在集成阶段单独报告。

## 七十八、代码质量

类型提示、清晰异常处理、避免超大函数、安全日志、合理 docstring、不过度设计。核心 proxy/sse 必须易读；SSE scanner 小型、纯粹、可测试。

## 七十九、中文文档要求

从 v0.1 正式开发开始所有正式项目文档正文统一中文（README、development/*、deployment/*、decisions/*、测试总结、阶段报告、使用/配置/数据库/API 说明）。英文仅用于代码、文件名、API 名称、参数名、技术术语、必要专有名词。

## 八十、Checkpoint 报告格式

每次阶段完成输出中文报告：1 本阶段目标；2 完成内容；3 新增文件；4 修改文件；5 测试结果；6 实际命令；7 当前运行状态；8 与规格差异；9 风险；10 下一阶段建议。不要只回复"完成了"。

## 八十一、最终验收

最终实现 OpenCode → EasyModelGate :3000 → llama.cpp :8080 → Qwen3.8，并全部通过：API Key、Key hash、Streaming、Non-stream、Tool Calling、Streaming Tool Calling、Client Disconnect、Usage、cached_tokens、TTFT、queue_wait、upstream_duration、RPM、Soft Token Quota、hour/day/week/month/custom range、user/key/model filter、SQLite WAL、restart persistence、OpenCode Agent、WebFetch、32K Agent workload。

## 八十二、最终停止点

完成 v0.1 全部验收后停止。不继续：64K context、128K context、Cloudflare Tunnel、ComfyUI、Web Admin（后续独立阶段）。最终提交《EasyModelGate v0.1 开发完成报告》（中文）。

## 八十三、现在开始执行

首先执行：1 保存本最终规格文件；2 更新 README 项目状态；3 归档 Phase 0.5 推荐 protocol samples；4 创建正式 micromamba 开发环境；5 创建正式项目骨架；6 开始 Phase 1。

完成 Checkpoint 1 后暂停并报告。第一阶段只做到 Checkpoint 1 就停下来，把它的执行报告发给我，审核后再进入 Proxy/SSE 阶段。
