# Checkpoint 1 执行报告（Phase 1-3）

- 日期：2026-08-26
- 范围：Phase 1 项目骨架+环境+文档+Schema；Phase 2 Security+User/Key CLI；Phase 3 /health+/v1/models
- 结论：**完成，待审核**

## 1. 本阶段目标

建立可运行的 v0.1 项目骨架：冻结规格落地、开发环境、数据库 schema v1、
API Key 安全体系（生成/哈希/鉴权）、管理 CLI、/health 与 /v1/models 端点。

## 2. 完成内容

- 冻结规格保存：docs/specifications/EasyModelGate-v0.1-Final-Specification.md
- micromamba 环境 easymodelgate-dev（Python **3.12.13** 精确版本），
  依赖全部命中冻结版本（fastapi 0.141.1 / starlette 1.6.0 / httpx 0.28.1 /
  uvicorn 0.52.4 / aiosqlite 0.22.1 / pydantic 2.13.4 / pytest 9.1.1 /
  pytest-asyncio 1.4.0）
- Schema v1：users/api_keys/backends/request_logs/settings + 规格 §46 全部索引；
  WAL/busy_timeout=5000/synchronous=NORMAL；幂等初始化与版本校验；
  时间统一 Unix 毫秒 UTC（ADR-0002）；backends.type=llamacpp（ADR-0003，
  启动种子行 api_key_ref 只存来源描述）
- API Key 体系：token_urlsafe(32) 生成、SHA-256 入库、key_prefix(12位)、
  展示一次性、日志脱敏 emg_xxxx****yyyy
- 鉴权依赖：Bearer 解析 → 前缀检查 → 哈希等值查询 → enabled/expires/user.enabled；
  错误统一 OpenAI 信封（401 invalid_api_key / key_disabled / key_expired，403 user_disabled）
- CLI：user create/list/disable/enable；key create/list/disable/enable
  （完整 Key 仅 stdout 一次 + 中文警示）；usage summary
  （period today/yesterday/24h/7d/week/month/all + from/to + hour/day/week/month 分桶 +
  user/key/model 过滤，中文表头，zoneinfo 时区分桶无硬编码偏移）
- 端点：GET /health → {"status":"ok","version":"0.1.0"}（§50 保持简单）；
  GET /v1/models 鉴权后代理上游并替换 Authorization；
  POST /v1/chat/completions 返回 501 占位（Phase 4 起）
- 后台任务基建：app.state.spawn（detached task + registry + shutdown flush），
  last_used_at 更新已按 §36 模式接入
- 文档中文化：README 重写、ADR-0002/0003/0004、schema-design.md、协议样本归档说明
- 协议样本归档：docs/protocol/llamacpp/ 共 9 个文件 + 中文 README（来源/日期/用途/脱敏说明）

## 3. 新增文件

```
docs/specifications/EasyModelGate-v0.1-Final-Specification.md
docs/protocol/llamacpp/{README.md + 9 个样本}
docs/decisions/ADR-0002-时间存储与时区.md
docs/decisions/ADR-0003-backend-type.md
docs/decisions/ADR-0004-SSE字节透传与扫描器.md
docs/development/schema-design.md
docs/development/Checkpoint-1-Report.md
LICENSE (Apache-2.0)  .gitignore  pyproject.toml  requirements.txt
environment.yml  configs/config.example.toml  scripts/init_dev_env.sh
easymodelgate/__init__.py __main__.py app.py cli.py config.py
easymodelgate/core/{auth,security,errors,ratelimit,concurrency,__init__}.py
easymodelgate/db/{database.py,schema.sql,dao.py,__init__.py}
easymodelgate/proxy/{upstream.py,headers.py,sse.py,__init__.py}
easymodelgate/routers/{public.py,__init__.py}
easymodelgate/services/{analytics.py,request_logging.py,usage.py,__init__.py}
tests/conftest.py tests/fake_upstream/server.py
tests/unit/{test_security,test_ratelimit}.py
tests/integration/{test_health_models,test_cli,test_db}.py
configs/upstream_key（本地密钥文件，chmod 600，不入库）
```

## 4. 修改文件

README.md（中文重写，含已实现/开发中/计划状态表）

## 5. 测试结果

- 自动测试：**23 passed**（security 4 / ratelimit 4 / db 4 / CLI 5 / health+models 鉴权矩阵 6）
- 真实环境冒烟（llama-server :8080 实测）：
  - GET /health → 200 {"status":"ok","version":"0.1.0"}
  - GET /v1/models 无鉴权 → 401 invalid_api_key 信封
  - 错误 Key → 401；chat 占位 → 501 not_implemented
  - 正确 Key → 200，真实上游模型列表透传成功（qwen3.8-local, n_ctx=32768）
  - backends 种子行正确（api_key_ref=file:configs/upstream_key，非密钥本体）
  - 服务端日志 grep 无完整 Key 泄漏

## 6. 实际命令（脱敏）

见 README「快速启动」；冒烟使用：
`$PY -m easymodelgate --config configs/config.toml serve`，
`curl -H "Authorization: Bearer $KEY" http://127.0.0.1:3000/v1/models`。
Key 从 CLI stdout 捕获至 shell 变量，未进入任何文档或日志。

## 7. 当前运行状态

服务可正常启停；data/easymodelgate.db 已含 1 用户 / 1 Key / 1 backend 种子。
冒烟结束后进程已停止，端口已释放。

## 8. 与规格差异

1. §50 upstream_reachable 未实现（规格允许"v0.1 优先简单"）——计划随 Phase 6 的
   上游健康逻辑一并考虑。
2. §21 日志脱敏格式示例为 emg_abcd****wxyz；因 v0.1 不存 Key 尾部，
   实际展示为 key_prefix 掩码形式（emg_xxxx****）。属展示细节，不影响安全语义。
3. usage summary 的 week 分桶采用 SQLite %W（周一为一周起点），与中文语境一致；
   ISO 周编号的跨年边界问题留待 Analytics 阶段细化。

## 9. 风险

- chat/completions 尚为 501 占位：在 Phase 4 落地前，任何指向 :3000 的真实
  Agent 流量都会失败（当前无此类流量）。
- 单连接 aiosqlite 串行写：last_used_at 高频更新未来可能需要节流
  （如仅当距上次 >60s 才写），Phase 9 观察后决定。
- conda base 的 pip 配置含失效镜像源告警（pypi.ngc.nvidia.com 解析失败但自动回退
  PyPI 成功），不影响本项目的独立环境。

## 10. 下一阶段建议

按冻结规格顺序进入 Phase 4-7（Checkpoint 2）：Non-stream Chat Proxy →
Streaming + SSE Scanner → Disconnect + Request Logging → Tool Calling 保真测试。
实现时直接复用 ADR-0004 已冻结的字节透传模式与 EXP-04 的断连模式。
