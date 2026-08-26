# llama.cpp 协议样本归档

## 来源

全部样本采集自 Phase 0.5 专项实验（`experiments/phase-0.5/`），
经审核后归档至本目录。原始实验文件保留在 experiments 下，未删除。

- 采集日期：2026-08-26
- 上游：本机 llama-server（systemd 单元 `llama-server.service`，
  描述 "Qwen3.8-27B on GPU 4-7"），地址 `127.0.0.1:8080`
- 模型标识：`qwen3.8-local`（GGUF Q6_K，n_ctx=32768）
- 客户端：Python 3.12.13 + httpx 0.28.1（micromamba 环境 easymodelgate-test）

## 用途与清单

| 文件 | 用途 |
|---|---|
| stream-without-stream-options.sse | 默认流式响应基线：无 usage chunk |
| stream-include-usage-true.sse | include_usage=true 时 usage 块出现在 [DONE] 前（choices==[]）的权威样例 |
| stream-include-usage-false.sse | 客户端显式 false 时无 usage 的对照证据 |
| non-stream-response.json | 非流式响应信封：usage / finish_reason / timings 结构 |
| tool-call-nonstream.json | 非流式 tool_calls 结构（arguments 为单个 JSON 字符串） |
| tool-call-stream.sse | delta.tool_calls 分片流式权威样例（arguments 分 5 片、id/name 仅首片） |
| plain-lines-obs.json | httpx aiter_lines 对普通流的逐行观测（EXP-02） |
| toolcall-lines-obs.json | httpx aiter_lines 对工具调用流的逐行观测（EXP-02） |
| disconnect_metrics.json | 客户端断连传播时延测量记录（约 2ms，EXP-04） |

这些样本是《EasyModelGate v0.1 最终开发规格》§12-§17 相关条款的事实依据；
实现或测试对 SSE / usage / tool calling 行为有疑问时，以本目录样本为准。

## 安全脱敏情况

- 样本仅含模型协议内容（chunk JSON、计时数据），不含任何 Authorization 头、
  API Key、用户隐私或系统路径。
- 采样脚本在运行时从既有 OpenCode provider 配置读取 upstream key 且从不打印；
  全部归档文件已通过密钥泄漏 grep 检查。

## 复现方式

参见各实验目录下 RESULT.md 的 Procedure 一节（命令已脱敏）：
`experiments/phase-0.5/exp01..exp04/*/RESULT.md`。
