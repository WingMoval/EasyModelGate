# EasyModelGate v0.1.0 — Release Notes

**发布日期：2026-08-26 · License：Apache-2.0**

## EasyModelGate 是什么

EasyModelGate 是放在客户端与本地模型服务器之间的一层轻量 API Gateway：

```
OpenCode / OpenAI-compatible client
        ↓
EasyModelGate :3000   ← 鉴权 · 限流 · 排队 · 日志 · 统计
        ↓
llama.cpp server      ← 任意 OpenAI-compatible 上游
```

它不加载模型、不管理 GPU，只做透明转发与治理。

## v0.1.0 核心能力

- **透明代理**：non-stream 与 streaming 均为字节级保真转发；
  SSE 事件不重序列化，Tool Calling 分片零拼接零改写
- **API Key 鉴权**：`emg_` Key、SHA-256 哈希存储、完整 Key 仅创建时展示一次
- **客户端断连保护**：断开后自动关闭上游连接，llama.cpp 即刻释放推理 slot
- **Usage 统计**：prompt/completion/total/cached_tokens 与 TTFT、排队耗时、上游耗时
- **限流与配额**：单实例内存 Fixed Window RPM；软性 Token 额度
- **Analytics**：hour/day/week/month/custom 聚合，支持 user/key/model 过滤
- **CLI 管理**：user/key 全生命周期与用量查询，无需 Web 界面
- **部署友好**：SQLite(WAL) 单文件存储；systemd 用户级/系统级模板；双 Provider 回滚通道

## Validation

- **118 automated tests** passed（fake upstream 体系，无需 GPU）
- 干净环境安装验证（全新 Python 3.12.13 环境从 requirements.txt 从零搭建）
- 真实 llama.cpp 功能回归（non-stream / stream / tool calling / usage）
- 真实 OpenCode A/B 八场景验证：基础问答、Streaming、Tool Calling、
  多轮工具、WebFetch、长 Agent、近 32K 工作流、Client Disconnect —— 全部 PASS
- 性能：网关额外开销 non-stream +16ms / stream TTFT +8.5ms（median）

## Supported Environment

| 项 | 要求 |
|---|---|
| OS | Linux |
| Python | 3.12 |
| 上游 | llama.cpp server（OpenAI-compatible API） |
| 硬件 | 无特殊要求（推理资源取决于上游） |

## Known Limitations

- llama.cpp 为正式验证的 backend；其它 OpenAI-compatible 服务未做兼容保证
- RPM 为单实例内存 Fixed Window，重启后窗口清零
- Token Quota 为软额度（允许单次请求超出后再拒绝后续请求）
- 暂无 Admin HTTP API / Web Dashboard（计划 v0.2）
- 不包含多机部署 / 高可用方案

## Documentation

- 快速开始与配置：见 [README](../README.md)
- 部署（systemd）：[docs/deployment/EasyModelGate-v0.1-Deployment.md](../deployment/EasyModelGate-v0.1-Deployment.md)
- 设计决策与阶段报告：[docs/decisions](../decisions/) · [docs/development](../development/)
- 协议样本：[docs/protocol/llamacpp](../protocol/llamacpp/)

## License

Apache License 2.0。第三方依赖均为 MIT / BSD 类宽松许可，
详见项目文档中的 License Check 说明。
