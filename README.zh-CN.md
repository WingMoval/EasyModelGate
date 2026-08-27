# EasyModelGate

[English](README.md) | 简体中文

轻量级本地模型 API Gateway。放在客户端与本地 llama.cpp server 之间，
提供 API Key 鉴权、限流、排队、用量统计与完整可观测性——
以字节级保真透明转发 Streaming 与 Tool Calling，不修改模型协议内容。

## 核心链路

```
OpenCode / OpenAI-compatible Client
        ↓
EasyModelGate  (:3000)
        ↓
llama.cpp server  (:8080)
        ↓
Local Model (Qwen 等)
```

## 核心原则：透明代理优先

EasyModelGate 不理解、不修改模型输出与 Tool Calling 内容。
它只负责：

- API Key 鉴权（SHA-256 哈希存储，完整 Key 仅创建时展示一次）
- RPM 限流（单实例内存 Fixed Window）
- 并发排队（`queue_wait_ms`）
- Usage 统计（prompt / completion / total / cached_tokens）
- TTFT 与 `upstream_duration_ms`
- 请求日志（不保存 prompt/response/reasoning/tool arguments）
- Analytics（hour / day / week / month / custom）
- Streaming 透明转发（字节级保真）
- Tool Calling 透明转发（零拼接、零重序列化）
- Client Disconnect 上游取消（断开即停止 GPU 推理）
- Soft Token Quota（软额度）
- SQLite（WAL）持久化

## 正式验证（v0.1.0）

以下场景已在真实 OpenCode + llama.cpp + Qwen 链路下全部通过：

- Non-stream
- Streaming（渐进式输出）
- Tool Calling
- Streaming Tool Calling（arguments 分片保真）
- Client Disconnect（上游即刻释放推理 slot）
- Queue（并发排队与 queue_wait_ms 观测）
- RPM（超限 429 + Retry-After）
- Soft Token Quota（soft overrun 后拒绝后续请求）
- Usage（含 cached_tokens）
- TTFT
- Analytics（ISO 周 / 时区边界正确）
- SQLite 重启持久化
- OpenCode Agent（多轮工具链）
- WebFetch Agent
- 近 32K Agent workflow

## 测试状态

**118 automated tests passed**

多数测试通过可编程 fake upstream 完成，
不依赖 GPU、不需要真实 llama.cpp 进程，
适合 GitHub Actions CI 直接运行。

## 支持环境

- Linux
- Python 3.12
- llama.cpp server（OpenAI-compatible API）

推荐使用 micromamba 管理 Python 环境；
micromamba 不是程序核心强制依赖。

## EasyModelGate 不负责

- 下载模型
- 加载 GGUF
- CUDA 安装
- NVIDIA Driver
- GPU 调度
- llama.cpp 编译

## 快速开始

```bash
# 获取代码
git clone https://github.com/WingMoval/EasyModelGate.git
cd EasyModelGate

# 创建 Python 3.12 环境
micromamba create -y -n easymodelgate python=3.12.13
$HOME/micromamba/envs/easymodelgate/bin/pip install -r requirements.txt

# 配置
cp configs/config.example.toml configs/config.toml   # 编辑 base_url / port 等

# upstream 密钥（二选一）
#   a) 写入文件：echo <key> > configs/upstream_key && chmod 600 configs/upstream_key
#   b) 环境变量：export EMG_UPSTREAM_API_KEY=<key>
# 上游未启用鉴权时不配置即可

# 初始化用户与 API Key
PY=$HOME/micromamba/envs/easymodelgate/bin/python
$PY -m easymodelgate --config configs/config.toml user create --username alice
$PY -m easymodelgate --config configs/config.toml key create --user alice \
    --name laptop          # 完整 Key 仅此次显示

# 启动服务（默认 :3000）
$PY -m easymodelgate --config configs/config.toml serve

# 验证
curl http://127.0.0.1:3000/health
curl http://127.0.0.1:3000/v1/models -H "Authorization: Bearer emg_xxx"
curl http://127.0.0.1:3000/v1/chat/completions \
     -H "Authorization: Bearer emg_xxx" -H "Content-Type: application/json" \
     -d '{"model":"<upstream-model>","messages":[{"role":"user","content":"hi"}]}'
```

## OpenCode 接入

在 OpenCode 配置中将 Provider 的 baseURL 指向：

```
http://127.0.0.1:3000/v1
```

apiKey 使用网关下发的 `emg_` Key。
同时建议保留一个直连 llama.cpp 的 Provider 作为回滚通道：
Gateway 出现异常时切换回直连即可，客户端无需其它改动。

## 安全原则

- SQLite 仅存 `key_prefix` 与 SHA-256 哈希；完整 Key 不落库
- 完整 Key 仅创建时展示一次；日志展示一律脱敏
- 日志不含 Authorization 头、prompt/response/reasoning/tool arguments 内容
- upstream 密钥独立文件存储（chmod 600）或环境变量注入

## 已知限制

- v0.1 正式验证的 backend 为 **llama.cpp**
- 其它 OpenAI-compatible backend 不属于 v0.1 正式兼容保证
- RPM 为单实例内存 Fixed Window
- 服务重启后 RPM window 清零
- Token Quota 为 Soft Quota（允许单次请求超出后拒绝后续请求）
- `/v1/models` 不计 RPM / Token Quota
- 无 Admin HTTP API
- 无 Web Dashboard
- 无 HA
- 无多机集群

## 文档资产说明

仓库同时保留以下内容，它们属于工程验证资产、设计证据与开发记录，
并非临时垃圾：

- `tests/` —— 118 项自动测试与 fake upstream
- `experiments/phase-0.5/` —— 协议与环境专项实验证据
- `docs/` —— 规格、决策记录、阶段报告、部署文档
- `docs/protocol/llamacpp/` —— llama.cpp 真实协议样本（脱敏）

## 文档索引

| 内容 | 路径 |
|---|---|
| **用户使用手册（完整 CLI 操作流程）** | **docs/USER_GUIDE.zh-CN.md** |
| 快速开始 / 配置 / CLI | 本文件 |
| 部署（systemd） | docs/deployment/EasyModelGate-v0.1-Deployment.md |
| 冻结规格 | docs/specifications/EasyModelGate-v0.1-Final-Specification.md |
| 设计决策 | docs/decisions/ |
| 协议样本 | docs/protocol/llamacpp/ |
| 阶段报告 | docs/development/ |

## License

Apache License 2.0
