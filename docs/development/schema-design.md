# EasyModelGate 数据库设计说明（schema v1）

> 本文档满足冻结规格 §28 的要求：在正式实现前明确一次时间单位约定。

## 时间单位（最终决定）

**所有表的所有时间字段 = Unix epoch 毫秒（INTEGER，UTC）。**

- `users.created_at`
- `api_keys.created_at / expires_at / last_used_at`
- `backends.created_at`
- `request_logs.started_at / finished_at`

理由与细节见 ADR-0002。全代码不允许混用秒。

## 时区

- 存储：永远 UTC。
- 展示/分桶：Python `zoneinfo` 按 `usage.timezone`（默认 Asia/Shanghai）计算
  偏移后处理；SQL 内不硬编码 "+8 hours"。

## 表清单（v1）

### users
id PK / username UNIQUE NOT NULL / display_name / enabled(0|1) / created_at(ms) / note

### api_keys
id PK / user_id FK→users.id / name / key_prefix(12位) / key_hash UNIQUE(SHA-256 hex) /
enabled / expires_at(ms, NULL=永不过期) / rpm_limit(NULL=不限) /
token_limit(NULL=不限，软额度) / token_used / created_at(ms) / last_used_at(ms)

### backends
id PK / name UNIQUE / type='llamacpp'（见 ADR-0003）/ base_url /
api_key_ref（密钥来源描述，非密钥本体）/ enabled / created_at(ms)

### request_logs（写入方在 Phase 6/9 接入）
见 schema.sql 注释；包含 queue_wait_ms / upstream_duration_ms / ttft_ms /
cached_tokens 等全部规格 §26 列；error_message 截断 ≤500 字符；
**不保存任何 prompt/response/reasoning/tool 内容**（规格 §27 强制隐私原则）。

### settings
key/value_json；含 schema_version=1。

## 索引（规格 §46）

- idx_rl_started(started_at)
- idx_rl_user_started(user_id, started_at)
- idx_rl_key_started(api_key_id, started_at)
- idx_rl_model_started(model, started_at)
- api_keys.key_hash UNIQUE、users.username UNIQUE（建表约束自带）

其余索引等待真实 query plan 再定，不预先堆砌。

## 运行参数

连接建立即执行：journal_mode=WAL / busy_timeout=5000 / synchronous=NORMAL /
foreign_keys=ON。初始化幂等：已存在的库重复执行建表脚本不会破坏数据；
settings.schema_version 与代码版本不一致时拒绝启动（走规格变更流程）。

## Token 软额度语义（§42）

请求前检查 token_used >= token_limit → 429 insufficient_quota；
请求完成后 token_used += total_tokens；允许单请求 soft overrun。
不做预留（reservation）、不预估 max_tokens。
