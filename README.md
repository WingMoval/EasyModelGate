# EasyModelGate

EasyModelGate v0.1.0

EasyModelGate — Lightweight Local Model API Gateway

中文：EasyModelGate：轻量级本地模型 API 网关

## 项目简介

EasyModelGate 是放在**客户端**与**本地模型服务器**之间的一层轻量 API Gateway。
它不加载模型、不管理 CUDA/GPU、不负责编译 llama.cpp；
只负责：API Key 鉴权、限流、排队、Usage 统计、请求日志、Analytics、
Streaming 与 Tool Calling 的透明转发。

## 目标链路（架构）

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

核心原则：**透明代理优先**。网关不理解、不修改模型内容与 Tool Calling，
只负责鉴权、安全、限流、排队、上游访问、透明转发、请求日志与用量统计。

## 当前状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0 | 同类项目技术调研 | 已完成（PASS） |
| Phase 0.5 | 协议与环境专项实测（5 项实验） | 已完成（PASS） |
| **Phase 1** | 项目骨架 + 环境 + 文档 + Schema | **已实现** |
| **Phase 2** | Security + User/Key CLI | **已实现** |
| **Phase 3** | /health + /v1/models | **已实现** |
| Phase 4 | Non-stream Chat Proxy | 已实现 |
| Phase 5 | Streaming + SSE Scanner | 已实现 |
| Phase 6 | Disconnect + Request Logging | 已实现 |
| Phase 7 | Tool Calling 保真测试 | 已实现 |
| Phase 8 | Semaphore + Queue Metrics | 已实现 |
| Phase 9 | Usage + cached_tokens + TTFT | 计划 |
| Phase 10 | Analytics | 计划 |
| Phase 11 | RPM + Soft Token Quota | 计划 |
| Phase 13 | 真实 OpenCode 集成测试 | 计划 |
| Phase 14 | systemd 部署 | 计划 |

冻结规格：`docs/specifications/EasyModelGate-v0.1-Final-Specification.md`

## 系统要求

- Linux + Python **3.12**（推荐 micromamba 管理；非必须依赖）
- 上游：任何 OpenAI-compatible 服务（正式验证对象为 llama.cpp server）
- EasyModelGate 不负责：下载模型、加载 GGUF、安装 CUDA、编译 llama.cpp、GPU 调度

## 快速开始

```bash
# 0) 获取代码
git clone https://github.com/<you>/EasyModelGate.git
cd EasyModelGate

# 1) 创建 Python 环境（micromamba 推荐，venv 亦可）
micromamba create -y -n easymodelgate-dev python=3.12.13
$HOME/micromamba/envs/easymodelgate-dev/bin/pip install -r requirements.txt

# 2) 准备配置与上游密钥
cp configs/config.example.toml configs/config.toml   # 按需修改
# upstream key 写入 configs/upstream_key（chmod 600），
# 或使用环境变量 EMG_UPSTREAM_API_KEY

# 3) 初始化用户与 Key
PY=$HOME/micromamba/envs/easymodelgate-dev/bin/python
$PY -m easymodelgate --config configs/config.toml user create --username alice
$PY -m easymodelgate --config configs/config.toml key create --user alice \
    --name laptop --rpm 60        # 完整 Key 仅此次展示

# 4) 启动服务
$PY -m easymodelgate --config configs/config.toml serve

# 5) 验证
curl http://127.0.0.1:3000/health
curl -H "Authorization: Bearer emg_xxx..." http://127.0.0.1:3000/v1/models
```

## 配置

TOML 文件（`configs/config.toml`，模板见 `configs/config.example.toml`）+
环境变量覆盖（`EMG_<段>_<字段>`，如 `EMG_SERVER_PORT=3001`）。

| 段 | 字段 | 说明 |
|---|---|---|
| server | host / port | 监听地址端口 |
| database | path | SQLite 路径（WAL 自动启用） |
| upstream | base_url / api_key_file / slots | 上游地址、密钥文件路径、并发槽位（对应 --parallel） |
| timeouts | connect / write / read / pool / total_request | 冻结值 5/60/None/10/1800 秒 |
| security | key_prefix | 客户端 Key 前缀（默认 emg_） |
| usage | timezone | 统计分桶时区（默认 Asia/Shanghai） |
| limits | max_client_concurrency | 网关最大并发连接 |

敏感信息不进配置文件：upstream key 只放 `configs/upstream_key`（chmod 600）
或环境变量 `EMG_UPSTREAM_API_KEY`。

## API

| 方法 | 路径 | 鉴权 | 状态 |
|---|---|---|---|
| GET | /health | 无 | 已实现 |
| GET | /v1/models | Bearer emg_ key | 已实现 |
| POST | /v1/chat/completions | Bearer emg_ key | 已实现（透明代理：non-stream + streaming + tool calling） |

错误统一 OpenAI-compatible 信封：
`{"error":{"message","type","param","code"}}`。

## CLI

```
python -m easymodelgate user create|list|disable|enable
python -m easymodelgate key  create|list|disable|enable
python -m easymodelgate usage summary [--period today|yesterday|24h|7d|week|month|all]
                                      [--from ... --to ...] [--group-by hour|day|week|month|none]
                                      [--user U] [--key PREFIX] [--model M]
python -m easymodelgate serve [--config PATH]
```

完整 Key 仅在 `key create` 时 stdout 展示一次。

## 测试

```bash
python -m pytest -q        # 当前基线：118 passed
```

覆盖：Auth、Non-stream、Streaming/SSE 字节保真、Tool Calling、Client Disconnect、
Queue/RPM/Quota、Usage、Analytics、SQLite 持久化。
大部分测试使用内置 fake upstream，**无需 GPU**。

## 已知限制

- v0.1 正式验证的 backend 为 llama.cpp；其它 OpenAI-compatible 服务未做兼容保证
- RPM 为单实例内存 Fixed Window，进程重启后窗口清零
- Token Quota 为软额度（允许单次请求超出后再拒绝），不做额度预留
- `/v1/models` 不计 RPM / Token Quota
- Web Dashboard 与 Admin HTTP API 尚未实现（计划 v0.2）
- 不包含多机部署 / 高可用

## 设计边界（重要）

- `/v1/models` 不计 RPM / Token Quota（仅 chat 端点限流）
- Token Quota 为 **Soft Quota**：不预留额度，允许单次请求超出后拒绝后续请求
- RPM 为进程内 Fixed Window（60s），**服务重启后窗口清零**
- Usage Analytics 仅提供 CLI（无 Admin HTTP API）
- Admin HTTP API / Web Dashboard 尚未实现（v0.2 计划）

## 安全原则

- SQLite 只存 `key_prefix` 与 `key_hash`（SHA-256），完整 Key 不落库
- 完整 Key 仅创建时展示一次；日志一律脱敏（`emg_abcd****wxyz`）
- 日志禁止出现 Authorization 头、完整 Key、prompt/response 内容
- request_logs 不保存任何用户内容（强制隐私原则）
- upstream 密钥独立文件存储（chmod 600），优先级：环境变量 > 文件

## 开发状态

Phase 1-14 全部完成：118 项自动测试全绿 · OpenCode A/B 八场景 PASS ·
systemd 长驻部署（用户级 unit，开机自启需运维执行 enable-linger，见部署文档）；chat 代理（non-stream/streaming/
tool calling/断连保护）已上线并通过真实 llama.cpp 验证。
Phase 8 及以后各阶段均已通过对应 Checkpoint 审核。

## 文档索引

- 冻结规格：docs/specifications/EasyModelGate-v0.1-Final-Specification.md
- Phase 0 调研：docs/research/EasyModelGate-v0.1-Phase0-Technical-Research.md
- Phase 0.5 实验：experiments/phase-0.5/REPORT.md
- 协议样本：docs/protocol/llamacpp/
- 架构决策记录：docs/decisions/
- 数据库设计说明：docs/development/schema-design.md
- 阶段报告：docs/development/

## License

Apache License 2.0（见 LICENSE）。仅学习参考项目的接口行为与设计思想，
未复制任何 AGPL 项目代码。
