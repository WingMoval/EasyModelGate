# ADR-0003：backends.type 取值定为 llamacpp

- 状态：已接受（2026-08-26）
- 关联规格：§25

## 背景

backends 表保留多后端抽象，但 v0.1 只有 llama.cpp 一种上游。
type 字段可选 openai-compatible 或 llamacpp 二选一。

## 决策

type = **llamacpp**。

理由：未来可能接入的 vLLM / Ollama / SGLang 虽然都是 OpenAI 兼容协议，
但各自有差异化行为（如 usage 默认值、tool calling 支持度、健康检查端点、
模型列表语义），ComfyUI 更是完全不同的异步任务范式。用具体类型名区分，
比笼统的 "openai-compatible" 更利于未来按类型挂载差异逻辑；
llama.cpp 的流式 usage 行为等事实依据已固化于 docs/protocol/llamacpp/。

## 后果

- v0.1 启动时若 backends 表为空，将以配置生成一条
  (name='local-llamacpp', type='llamacpp', base_url=配置值,
   api_key_ref=密钥来源描述) 种子行；api_key_ref 只存"来源描述"
  （如文件路径或 env 变量名），绝不存密钥本身。
