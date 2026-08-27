# EasyModelGate Web Foundation 设计

Web Dashboard MVP 的架构冻结文档（Checkpoint 2）

状态：**FROZEN（待人工审核）** · 适用版本：v0.1.x · 本文档不引入任何代码变更

---

## 1. 当前架构分析

### 1.1 现状模块图（基于 v0.1.0 实际代码）

```
easymodelgate/
├── cli.py                 # 参数解析 + 全部管理业务逻辑 + 终端渲染（367 行）
├── app.py                 # FastAPI 组装、lifespan、spawn
├── config.py              # TOML + EMG_* 环境变量加载
├── routers/public.py      # /health /v1/models /v1/chat/completions
├── core/
│   ├── auth.py            # Public API Bearer 鉴权（require_auth）
│   ├── security.py        # generate_key / hash_key / mask_key
│   ├── errors.py          # ApiError + OpenAI 风格错误 envelope
│   ├── ratelimit.py       # FixedWindowRpmLimiter（内存）
│   └── concurrency.py     # UpstreamSlots 排队
├── db/
│   ├── database.py        # aiosqlite 单连接 + WAL + schema 版本闸门
│   ├── dao.py             # users / api_keys 数据访问（94 行）
│   └── schema.sql         # users / api_keys / backends / request_logs / settings
├── services/
│   ├── analytics.py       # SummaryFilter + summary()：完整聚合算法 ★
│   ├── request_logging.py # persist_request_log（日志+token 原子累加）★
│   └── usage.py           # 占位
└── proxy/                 # relay / sse / headers / upstream（纯透传链路）
```

### 1.2 十个关键问题答案

| # | 问题 | 答案 |
|---|---|---|
| 1 | user create/list/enable/disable 逻辑在哪 | `cli.py:_user()`（124-145 行）：重名检查、启停、输出格式化全在 CLI handler；DAO 仅有原子操作 |
| 2 | key create/list/enable/disable/set-limits 逻辑在哪 | `cli.py:_key()`（150-217 行）：Key 生成编排、前缀唯一匹配、set-limits 合并语义在 CLI；**set-limits 的 UPDATE SQL 直接写在 cli.py:211-214（绕过 DAO，唯一一处 CLI 直写 SQLite）** |
| 3 | usage summary 逻辑在哪 | 聚合算法在 `services/analytics.py:summary()`（服务层，可复用）；**period→时间范围解析、user/username→id、key 前缀→id 解析在 `cli.py:_usage()`（232-288 行）** |
| 4 | CLI 是否直接调用 DAO | 是（经 `_db_*` 薄封装转调 `db/dao.py`） |
| 5 | CLI 是否直接写 SQLite | 有且仅有一处：cli.py:211-214 的 `UPDATE api_keys SET rpm_limit...`（set-limits） |
| 6 | 是否已有可复用的 service 层 | 部分：`analytics.summary`、`request_logging.persist_request_log` 可直接复用；**Users/Keys 没有 service 层** |
| 7 | 只存在于 CLI handler 的逻辑 | 用户名重名校验、expires_in_days→毫秒换算、前缀唯一匹配报错、set-limits 的 clear 合并语义、period 解析、所有终端渲染 |
| 8 | Web MVP 前应抽取成 service 的逻辑 | 见 §2.2（UserService / KeyService / UsageService 三个薄 service + period 解析共享化 + 补 4 个 DAO 函数） |
| 9 | 可直接复用的 DAO | `dao.py` 全部现有函数（users/api_keys 读写、by-id 启停、hash 查询、前缀查询） |
| 10 | 绝对不允许 Dashboard 重写的代码 | `analytics.summary`（统计算法唯一真相）、`core/security`（Key 生成/哈希/脱敏）、`core/errors`（envelope）、RPM/Quota 语义、`request_logging` |

### 1.3 CURRENT_SERVICE_REUSE_ANALYSIS 结论

复用成熟度：**usage 链路 ~90% 可复用；users/keys 链路 0%（逻辑困在 CLI）**。
这是 Web MVP 前唯一需要结构性处理的问题，且规模很小（预计净增 <250 行）。

---

## 2. 业务逻辑复用分析（Shared Service 策略）

### 2.1 冻结的分层

```
CLI ────────────┐
                ├──► Services（薄，纯业务规则，无 print / 无 HTTP）──► DAO ──► SQLite
Admin API ──────┘
Public API（relay 链路）──► core/ + proxy/（不经过管理 services，保持不动）
```

硬性规则：

- CLI 与 Admin API **共用同一 service 层**，禁止各维护一套业务规则
- Service 函数返回数据/抛 `ServiceError`，**不做 print、不感知 HTTP**；
  渲染（终端表格 vs JSON）属于调用方
- Public API（/v1/*）链路完全不引入 Admin 代码，保持透明代理不变

### 2.2 下一阶段要抽取的最小 service 集合（Checkpoint 3 Step 1）

| 新模块 | 承接的现有逻辑 | 说明 |
|---|---|---|
| `services/user_service.py` | cli `_user()` 的重名校验/创建/启停 | `create_user(username, display_name, note) -> UserRow`（重复抛 `AlreadyExists`）、`list_users()`、`set_enabled(user_id, enabled)` |
| `services/key_service.py` | cli `_key()` 的生成编排、expires 换算、前缀匹配、**set-limits SQL（从 cli.py 移入 DAO）** | `create_key(user_id, name, rpm, token_limit, expires_in_days) -> (key_id, full_key, masked)`、`list_keys()`、`set_enabled(key_id, bool)`、`set_limits(key_id, rpm|CLEAR, token_limit|CLEAR)`、`get_key(key_id)` |
| `services/usage_service.py` | cli `_usage()` 的 period→范围解析 | `resolve_period(period, from, to, tz) -> (start_ms, end_ms, default_group)`；`query(filter)` 直接转调 `analytics.summary` |
| `db/dao.py` 增补 | — | `get_key_by_id`、`set_key_limits_by_id`、`set_user_enabled_by_id`、`list_request_logs(过滤+limit/offset)`、`count_recent_errors(区间)` |

约束：CLI 保持现有对外行为与输出**逐字节不变**（118 测试为闸门），
`usage.py` 占位文件由 `usage_service.py` 取代或删除。

### 2.3 目标结构（冻结命名）

```
EasyModelGate
├── Public API（不动）      /health · /v1/models · /v1/chat/completions
├── Admin API（新）         /admin/api/*
├── Web UI（新）            /admin/*（Jinja2 服务端渲染）
├── Services                user_service · key_service · usage_service
│                           · analytics · request_logging · system_service
├── DAO（唯一 SQL 出口）     db/dao.py（增补后成为全部管理 SQL 的家）
└── SQLite（schema v1，不动）
```

---

## 3. Dashboard MVP 页面范围（冻结）

| 页面 | 路由 | 说明 |
|---|---|---|
| Login | `/admin/login` | 入口，不在侧边栏 |
| Overview | `/admin` (=`/admin/overview`) | 见 §4 |
| Users | `/admin/users` | 见 §5 |
| API Keys | `/admin/keys` | 见 §6 |
| Usage | `/admin/usage` | 见 §8 |
| System | `/admin/system` | 见 §9 |

**WEB_ADMIN_SERVER_CONTROL = FORBIDDEN**（任何服务器管理动作，见 §9）

## 4. Overview 页面（冻结）

- Gateway Status：进程存活 + version（能打开页面即 ok，来自 SystemService）
- Backend Status：对 `upstream.base_url/health` 的一次轻量探测（复用
  `app.state.upstream.client`，超时沿用 `timeouts.connect`）
- Today 卡片：Requests / Success Rate / Total Tokens / Avg TTFT
  （= `analytics.summary` 今日 TOTAL 行，零新算法）
- Usage Trend：今日按小时 + 近 7 天按天两组 buckets（同一 `summary()`）
- 可选：Active Keys 计数（`SELECT COUNT(*) WHERE enabled=1`）
- 明确不做：GPU / CPU / RAM / Disk / systemd / 进程管理

## 5. Users 页面（冻结）

支持：list / create / enable / disable。
展示：id · username · display_name · enabled · created_at · note（schema 已有 note 列）。
不做：delete user · role · 用户密码 · organization · RBAC。

## 6. API Keys 页面（冻结）

支持：list / create / enable / disable / set RPM / set Token Quota / clear RPM / clear Token Quota。
展示：id · user · name · masked display（`mask_key(key_prefix)`）· enabled · rpm ·
token_used · token_limit · expires_at · last_used_at。

冻结规则：

1. **管理操作一律用 `key_id`**（路径参数），禁止 Dashboard 用前 12 字符做内部标识
2. 完整 Key **只在 create 成功响应中出现一次**；前端一次性弹窗 + "我已保存"确认
3. Admin API 永远不提供 `GET full key`（数据库本就只存哈希，此条同时冻结 API 面）
4. CLI 改 `--id` 属于后续 CLI Cleanup，本阶段不动 CLI

## 7. Key ID 资源模型（冻结）

实测 schema：`api_keys.id INTEGER PRIMARY KEY AUTOINCREMENT` ✓ 整数 ✓ 稳定
（AUTOINCREMENT 防复用）✓ 已有 `set_key_enabled_by_id` 等 by-id DAO ✓。

**ADMIN_KEY_IDENTIFIER = api_keys.id**

## 8. Usage 页面与数据模型（冻结）

- period：`today / yesterday / 24h / 7d / week / month / all` + custom（`from/to`）
- group_by：`hour / day / week / month / none`
- 过滤：Admin API 用 `user_id` / `key_id`（稳定 ID）；`model` 无独立 ID，继续用字符串
- 时间范围语义 `[start, end)`、时区（`usage.timezone`）、week=ISO 周——
  **全部沿用 `resolve_period` + `analytics.summary`，禁止第二套统计算法**

### 8.1 Summary 响应契约

`GET /admin/api/usage/summary` → 单次 `analytics.summary()` 调用拆出两部分：

```json
{
  "summary": {
    "requests": 0, "success": 0, "failed": 0, "success_rate": 0.0,
    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    "cached_tokens": 0,
    "avg_duration_ms": null, "avg_queue_wait_ms": null, "max_queue_wait_ms": null,
    "avg_upstream_ms": null, "avg_ttft_ms": null
  },
  "buckets": [
    {"bucket": "2026-08-28T10:00", "requests": 0, "success": 0, "failed": 0,
     "total_tokens": 0, "avg_ttft_ms": null}
  ]
}
```

字段映射：`success_rate = success/requests`（requests=0 时为 null）、
`avg_upstream_ms` ← `avg_upstream_duration_ms`（JSON 层改名，内部算法不动）、
buckets 为分桶行（去掉 TOTAL 行，它即 summary）。
`group_by=none` 时 buckets 为空数组。

## 9. System 页面（冻结）

提供：version · gateway health · backend health（实时轻探测）·
database health（`SELECT 1`）· uptime（lifespan 记录启动时刻即可）·
近 24h 错误统计 + 最近错误列表（`request_logs` 按 `status_code>=400`）。

FORBIDDEN（永久禁止进入 Web Admin）：restart llama.cpp / restart 网关 /
systemd 操作 / 文件系统读写 / GPU 控制 / 模型加载卸载 / OS 修改 / mount 修改 /
shell execution。

## 10. Admin Authentication（方案对比与选型）

前提：single-admin，无 multi-admin/RBAC/OAuth/SSO。

| 维度 | A. 静态 Admin Token | B. 密码 + 服务端 Session Cookie |
|---|---|---|
| 浏览器体验 | 差：HTML 导航无法带 Authorization 头，只能 localStorage+纯 JSON SPA 或把 token 塞 URL（都不可接受） | 好：登录一次，页面直接可用 |
| 登出 | 无真登出（token 长期有效，只能全量吊销） | 服务端删 session，立即失效 |
| Session expiry | 无 | 有（默认 12h，滑动可选） |
| CSRF | 天然免疫（自定义头） | 需处理：SameSite=Lax + Origin 校验（§11） |
| XSS 后果 | token 可被 JS 窃取且长期有效 | HttpOnly cookie JS 读不到；session 短期 |
| Secret 存储 | 明文长期 token 落配置文件 | 只存 scrypt 哈希（§11） |
| 部署复杂度 | 最低 | 低（自研 ~80 行，无新依赖） |
| 额外依赖 | 无 | 无（hashlib.scrypt 为标准库） |

**选型：B**。理由：Dashboard 是浏览器产品，A 的 SPA-only 限制与
"无登出/无过期"违背安全底线；B 用标准库即可完成，与项目轻量定位一致。
不引入 Starlette SessionMiddleware（避免 itsdangerous）、不引入任何认证框架。

实现要点（Checkpoint 3 Step 2）：

- `POST /admin/api/auth/login` `{username, password}` → 校验 scrypt →
  `Set-Cookie: emg_session=<secrets.token_urlsafe(32)>`
- 服务端进程内 `dict[session_id] -> expires_at`，惰性清理；
  重启全员掉线重登（MVP 接受，见 §17 风险 R3）
- 鉴权依赖 `require_admin`：解 cookie → 查表 → 过期即 401
- `POST /admin/api/auth/logout`；`GET /admin/api/auth/me`（前端判登录态）
- login 限速：进程内简单计数（如同一 IP 每分钟 ≤10 次失败），防爆破

## 11. Admin Credential Storage（冻结设计）

- 存储位置：现有 `settings` 表，`key='admin_credential'`，
  `value_json = {"kdf":"scrypt","N":2**15,"r":8,"p":1,"salt":"<b64>","hash":"<b64>","updated_at":<ms>}`
  —— **只存派生密钥，不存明文**，零 schema 变更
- 未初始化时 Admin API 一律 **503 `admin_not_initialized`（fail-closed）**，
  Login 页提示运行初始化命令
- 首次初始化（未来实现，命名冻结为 `easymodelgate admin init`）：
  交互式 `getpass` 读密码（支持 `--password-stdin` 供脚本），写 settings 表；
  已存在时需 `--force` 才覆盖
- 禁止清单：明文密码进 SQLite / 明文进 Git / 写入 config.example.toml /
  出现在任何日志（含 debug）；scrypt 参数与哈希可安全入库
- 本阶段不实现 admin init，只冻结契约

## 12. Session / CSRF 安全策略（冻结）

| 项 | 决定 |
|---|---|
| Cookie 属性 | `HttpOnly` · `SameSite=Lax` · `Path=/admin` · `Max-Age=43200`（12h，配置项 `admin.session_ttl`，未来） |
| Secure | 仅 HTTPS 部署（`server.tls` 未来出现时）置位；http localhost 默认不置 |
| 过期 | 服务端绝对过期（登录时刻+TTL）；不做滑动 |
| 登出 | 删除服务端 session + `Set-Cookie: emg_session=; Max-Age=0` |
| CSRF | SameSite=Lax 拦截跨站 POST/PATCH 携带 cookie；再叠加对所有非 GET `/admin/api/*` 做 **Origin 校验**（同源或缺 Origin 放行）——不引入 CSRF 库 |
| XSS | 页面全部 Jinja2 autoescape；管理数据不含 HTML 注入面；HttpOnly 保证 cookie 不可读 |
| 0.0.0.0 暴露 | 文档必须警示：Admin 暴露在非环回地址 = 把管理面交给整个网络；仅密码一项防线，强烈建议反代+TLS 或防火墙限制 |

即使只监听 localhost / LAN，**也不取消 Admin Authentication**。

## 13. Admin API 契约（冻结清单）

约定：JSON 错误 envelope 复用 `core/errors` 形状（§15）；
全部 `/admin/api/*` 需登录（login 与 me 除外）。

### Auth

| Method | Path | Purpose | Body / Query | Response | Errors |
|---|---|---|---|---|---|
| POST | `/admin/api/auth/login` | 登录，下发 session cookie | `{username,password}` | `{username}` | 401 bad_credentials · 429 login_rate_limited · 503 admin_not_initialized |
| POST | `/admin/api/auth/logout` | 登出 | — | `{ok:true}` | 401 |
| GET | `/admin/api/auth/me` | 当前登录态 | — | `{username}` | 401 |

### Users

| Method | Path | Purpose | 参数 | Response | Errors |
|---|---|---|---|---|---|
| GET | `/admin/api/users` | 列表 | — | `[{id,username,display_name,enabled,created_at,note}]` | 401 |
| POST | `/admin/api/users` | 创建 | `{username,display_name?,note?}` | 同上一行单对象 | 401 · 422 校验 · 409 重名 |
| POST | `/admin/api/users/{id}/enable` | 启用 | — | 单对象 | 401 · 404 |
| POST | `/admin/api/users/{id}/disable` | 停用 | — | 单对象 | 401 · 404 |

### Keys

| Method | Path | Purpose | 参数 | Response | Errors |
|---|---|---|---|---|---|
| GET | `/admin/api/keys` | 列表 | `user_id?` | `[{id,user_id,user,masked_key,name,enabled,rpm_limit,token_used,token_limit,expires_at,last_used_at}]`（**无 key_hash/key_prefix 原文，永不含完整 Key**） | 401 |
| POST | `/admin/api/keys` | 创建 | `{user_id,name?,rpm?,token_limit?,expires_in_days?}` | `{...,full_key:"emg_..."}` ← **唯一一次返回完整 Key** | 401 · 404 user 不存在 · 422 |
| GET | `/admin/api/keys/{id}` | 详情 | — | 列表单对象形状 | 401 · 404 |
| POST | `/admin/api/keys/{id}/enable` `/disable` | 启停 | — | 单对象 | 401 · 404 |
| PATCH | `/admin/api/keys/{id}/limits` | 改限额 | `{rpm?,token_limit?,clear_rpm?,clear_token_limit?}` | 单对象 | 401 · 404 · 422（rpm<1 等） |

### Usage / Overview / System / Requests

| Method | Path | Purpose | Query | Response | Errors |
|---|---|---|---|---|---|
| GET | `/admin/api/usage/summary` | 聚合 | `period \| from,to` · `group_by` · `user_id` · `key_id` · `model` | §8.1 契约 | 401 · 422（非法 period/时间） |
| GET | `/admin/api/overview` | Overview 一次取齐 | — | `{gateway,backend,today,buckets_hourly,buckets_daily,active_keys}` | 401 |
| GET | `/admin/api/system` | System 页 | — | `{version,gateway,backend,database,uptime_seconds,errors_24h,recent_errors[]}` | 401 |
| GET | `/admin/api/requests` | 最近请求 | `limit(≤200,默认50) · offset · user_id · key_id · status_class(2xx/4xx/5xx) · error_only` | `{total,items:[metadata]}` | 401 · 422 |

边界：`/admin/api/*` 不注册 `/v1/*` 路由的任何依赖；
`/v1/*` 不感知 admin（`create_app` 仅新增 `include_router(admin_router)`）。

## 14. Recent Requests 安全边界（冻结）

`GET /admin/api/requests` 只允许返回 request_logs 现有元数据列：
request_id · started_at · user/key id+名称 · model · endpoint · status_code ·
upstream_status_code · error_type · token 四项 · duration/queue_wait/upstream/ttft ·
stream · finish_reason · client_ip · input/output_bytes。

**不得返回（也不得将来存储）**：prompt · response · reasoning · tool arguments ·
任何请求/响应体内容。现状天然满足：request_logs 根本没有内容列
（content not stored by default 原则延续）。error_message 截断 500 字符后
可返回（已是错误诊断所需最小集，日志同源）。

## 15. Admin 错误模型（冻结）

复用 `{"error":{"message","type","param","code"}}` envelope，type 取 admin 语义：

| 状态 | code 例 | 场景 |
|---|---|---|
| 400 | `bad_request` | JSON 无法解析 |
| 401 | `unauthenticated` · `bad_credentials` | 无/过期 session；登录密码错 |
| 403 | `forbidden` | Origin 校验失败 |
| 404 | `not_found` | user/key/request id 不存在 |
| 409 | `already_exists` | 用户名重复 |
| 422 | `validation_error` | 字段校验失败（param 指向字段） |
| 429 | `login_rate_limited` | 登录爆破限速 |
| 500 | `internal_error` | 兜底（不回显异常详情） |
| 503 | `admin_not_initialized` | 未执行 admin init |

Pydantic 校验失败统一映射 422（Admin 路由使用 FastAPI 依赖校验时，
需在 admin 子应用内覆写 RequestValidationError handler——
避免影响 Public API 现有 400/422 行为，见 §17 R4）。

## 16. Frontend Stack / 路由 / Schema / 性能（冻结）

**WEB_FRONTEND_STACK = FastAPI + Jinja2 服务端渲染 + Vanilla JS（<200 行）+ 单文件 CSS**

- Jinja2 **当前未安装**，Checkpoint 3 需新增依赖 `jinja2`（纯 Python、无传递依赖冲突、
  Starlette `Jinja2Templates` 官方集成路径）——是 MVP 唯一新增依赖
- 零 Node / npm / React / Vue / Vite / Webpack / Tailwind
- 趋势图：内联 SVG 折线/柱（服务端算好坐标，无图表库）

**WEB_ROUTE_STRUCTURE**：

- `/admin/*`：HTML 页面（Jinja2）
- `/admin/api/*`：JSON API（页面 JS fetch 调用）
- `/v1/*` + `/health`：Public API，严格分离，不共享鉴权与错误语义

**WEB_MVP_SCHEMA_CHANGE_REQUIRED = NO**

逐项核对：Users ✓（含 note 列）· Keys ✓（id/prefix/name/enabled/rpm/limit/used/
expires/last_used 全存在）· Usage ✓（request_logs 覆盖全部聚合列 + 4 个索引支撑
过滤查询）· Overview ✓（聚合复用）· System ✓（version 来自代码，admin
credential 走 settings 表，uptime 进程内存）· Recent Requests ✓（request_logs
本身）。需要新增的仅是 DAO 查询函数，**无 DDL**。

性能边界：列表一律 `limit`（默认 50 / 上限 200）+ offset 分页；requests 查询
必须带 limit 且默认按 `started_at DESC`（走 `idx_rl_started`）；usage custom
range 跨度上限 92 天（超限 422，防止全历史扫描）；Overview 固定 today/7d
聚合，不做全历史；**无 Redis / cache / worker / Celery**。

## 17. Web MVP Exclusions（冻结清单）

Multi Admin · RBAC · OAuth · SSO · Multi Backend UI · Multi Node · Audit Center ·
GPU 管理 · 模型管理（加载/卸载） · Server Shell · systemd 管理 · 文件系统浏览 ·
Prompt Viewer · Response Viewer · Reasoning Viewer · Tool Argument Viewer ·
WebSocket 实时推送 · Prometheus · Grafana · React · Vue · Node 工具链 ·
删除用户 / 删除 Key（只 disable） · Key 编辑（只 limits/启停） ·
用户自助改密（Admin 密码只能 CLI init 重置）。

## 18. 实施顺序（Checkpoint 3 使用）

1. **Service extraction**：`user_service` / `key_service` / `usage_service`
   + DAO 增补 + set-limits SQL 下移 DAO；CLI 改为转调；118 测试逐字保行为
2. **Admin Authentication**：admin init CLI + scrypt + login/logout/me + session +
   Origin/CSRF + login 限速（含单测）
3. **Admin API Users / Keys**
4. **Admin API Usage / Overview / System / Requests**
5. **Dashboard Layout + Login 页**（Jinja2 基座、侧边栏、session 判态）
6. **Users UI**
7. **Keys UI**（含 full-key 一次性弹窗）
8. **Usage UI**（表格 + 内联 SVG）
9. **Overview / System UI**
10. **集成测试**（登录→建用户→建 Key→调用→用量→停用 全链路 +
    未登录 401 矩阵 + Origin 校验矩阵）+ 隐私检查 + 全量回归

每步独立可测、独立 commit；Step 1 先动代码但必须全绿后才进 Step 2。

## 19. Risks

| # | 风险 | 缓解 |
|---|---|---|
| R1 | Service 抽取破坏 CLI 行为 | 118 测试 + 输出快照抽查；抽取纯搬运不改语义 |
| R2 | Admin API 与 relay 同进程，admin 重查询占用事件循环 | usage 聚合 O(行数) 且时间范围有上限；requests 强制 limit；探测类请求带短超时 |
| R3 | session 存内存，网关重启全员掉线 | MVP 接受（文档声明）；未来需要再议（加 session 表需 schema 评审） |
| R4 | 覆写 RequestValidationError handler 泄漏到 Public API | admin 路由用独立 `APIRouter` + 显式 pydantic 手动校验或子应用级 exception handler，Step 2 先做 spike 验证隔离性 |
| R5 | `server.host=0.0.0.0` 暴露管理面 | 部署文档强制警示 + System 页显示当前监听地址（非环回时红字警告） |
| R6 | admin 请求挤占 `limit_concurrency` 配额 | 接受（默认 64，单机低并发）；不做 admin 专用配额 |
| R7 | settings 表新增 `admin_credential` 键与旧库兼容 | 只 INSERT/UPDATE 新键，零迁移风险；schema_version 保持 1 |
| R8 | scrypt N=2^15 在极低端设备登录稍慢（~50ms） | 可接受；参数存库便于将来升级 |

## 20. Go / No-Go 结论

- 复用分析：service 缺口小且边界清晰（3 个薄 service + 5 个 DAO 函数）
- Schema：零变更；Public API：零侵入；依赖：仅 +jinja2
- 安全模型（scrypt + HttpOnly/Lax cookie + Origin 校验 + fail-closed）
  与项目轻量定位匹配

**READY_FOR_WEB_MVP = YES** —— 按 §18 顺序进入 Checkpoint 3。
