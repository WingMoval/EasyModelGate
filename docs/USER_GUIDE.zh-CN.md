# EasyModelGate 用户指南

EasyModelGate v0.1.x CLI 使用与接入指南

本指南面向第一次使用 EasyModelGate 的用户，按章节顺序从头执行即可完成从安装到日常管理的全部操作。文中命令均基于 v0.1.0 实际 CLI 验证。

约定：

- `<PROJECT_ROOT>`：你克隆本项目的目录
- `<EMG_API_KEY>`：网关签发的 `emg_...` 完整 API Key（占位符）
- `<UPSTREAM_API_KEY>`：上游模型服务的 API Key（占位符）
- `<MODEL_NAME>`：上游实际暴露的模型名（占位符）
- 所有命令默认在项目根目录、且已激活 Python 3.12 环境的条件下执行

---

## 1. EasyModelGate 是什么

```
OpenCode / OpenAI-compatible Client
        ↓
EasyModelGate :3000
        ↓
API Key 鉴权 / RPM 限流 / Token Quota / 并发排队
        ↓
Usage 统计 / 请求日志 / CLI Analytics
        ↓
OpenAI-compatible Backend（如 llama.cpp :8080）
```

EasyModelGate 是一个 **API Gateway，不是模型推理引擎**。

它不会：

- 修改模型回答内容
- 重写或重组 Tool Calling
- 重新序列化 SSE 流（流式响应按字节透传）

它主要负责：

- API Key 鉴权（每个使用者一把独立 Key）
- RPM 限流与 Token 软额度
- 并发排队（保护只有一个推理槽位的本地后端）
- 用量统计与请求日志（SQLite 持久化）
- 上游代理与客户端断连时的上游取消

## 2. 使用前准备

要求 **Python 3.12**。

```bash
cd <PROJECT_ROOT>
python -m pip install -r requirements.txt
python -m pip install -e .
```

第二条命令安装 EasyModelGate 本体。跳过它会导致后续命令报
`ModuleNotFoundError: No module named 'easymodelgate'`。

验证安装：

```bash
python -m easymodelgate --help
```

## 3. 准备配置

```bash
cp configs/config.example.toml configs/config.toml
```

`configs/config.toml` 通常只需要改这几项：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `server.host` / `server.port` | `127.0.0.1` / `3000` | 网关监听地址 |
| `database.path` | `data/easymodelgate.db` | SQLite 位置（自动创建） |
| `upstream.base_url` | `http://127.0.0.1:8080` | 后端模型服务地址 |
| `upstream.api_key_file` | `configs/upstream_key` | 上游 Key 文件路径；文件不存在且未设环境变量时视为上游无鉴权 |
| `upstream.slots` | `1` | 对应 llama.cpp `--parallel` 槽位数 |
| `timeouts.total_request` | `1800.0` | 单请求全生命周期上限（秒） |
| `timeouts.queue_timeout` | `120.0` | 排队等待上限，超时返回 503 |
| `usage.timezone` | `Asia/Shanghai` | CLI 统计输出的时区 |

任何字段都可以用环境变量 `EMG_<段>_<字段>` 覆盖，例如
`EMG_SERVER_PORT=3001`、`EMG_DATABASE_PATH=data/prod.db`。

## 4. 配置上游 Key

上游 Key 是 **EasyModelGate 访问你的模型服务** 用的凭据，
与使用者拿到的 `emg_` Key 完全是两回事：

```
Client
  │  Authorization: Bearer emg_xxx        ← 用户 Key（网关签发）
  ▼
EasyModelGate
  │  Authorization: Bearer <UPSTREAM_API_KEY>   ← 上游 Key（你配置）
  ▼
llama.cpp / backend
```

两种配置方式，二选一：

**A. 文件方式（推荐）**

```bash
printf '%s' '<UPSTREAM_API_KEY>' > configs/upstream_key
chmod 600 configs/upstream_key
```

**B. 环境变量方式**

```bash
export EMG_UPSTREAM_API_KEY='<UPSTREAM_API_KEY>'
```

若上游服务本身不校验 Key（本地裸 llama.cpp 常见），两种方式都不做即可，网关不会向上游发送 `Authorization` 头。

## 5. 启动 EasyModelGate

```bash
python -m easymodelgate --config configs/config.toml serve
```

另开终端验证：

```bash
curl http://127.0.0.1:3000/health
```

正常返回：

```json
{"status":"ok","version":"0.1.0"}
```

即表示网关已启动。生产环境（systemd 托管）见 `docs/deployment/`，本指南不展开。

## 6. 创建第一个用户

```bash
python -m easymodelgate --config configs/config.toml user create --username alice --display-name "Alice"
```

输出：

```
用户已创建：id=1  username=alice
```

User 是网关内部的逻辑使用者身份。**用户本身不能直接调用 API**，
必须给用户创建 API Key（下一节）。

查看与启停：

```bash
python -m easymodelgate --config configs/config.toml user list
python -m easymodelgate --config configs/config.toml user disable --username alice   # 该用户所有 Key 立即不可用
python -m easymodelgate --config configs/config.toml user enable  --username alice
```

## 7. 创建 API Key

```bash
python -m easymodelgate --config configs/config.toml key create \
  --user alice \
  --name laptop \
  --rpm 60
```

带 Token 软额度与过期时间的例子：

```bash
python -m easymodelgate --config configs/config.toml key create \
  --user alice \
  --name opencode \
  --rpm 60 \
  --token-limit 5000000 \
  --expires-in-days 90
```

输出形如：

```
请立即保存，该 Key 后续无法再次查看。

emg_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

标识：emg_xxxx****xxxx   key_id=1   user=alice
```

> **⚠ 完整 `emg_` Key 只在创建时展示这一次，之后任何命令都查不到。**
> 请立即保存到密码管理器 / Secret Manager / 环境变量。
> 严禁写入 Git 仓库。

`--name` 是给人看的备注（如 `laptop`、`opencode`、`server-a`），不参与鉴权。

## 8. 查看已有 Key

```bash
python -m easymodelgate --config configs/config.toml key list
python -m easymodelgate --config configs/config.toml key list --user alice
```

输出字段：

| 字段 | 含义 |
|---|---|
| `id` | Key 内部 ID |
| `user` | 所属用户名 |
| `name` | 创建时的备注名 |
| `key_prefix` | 打码的 Key 前缀（仅用于辨认，不能直接当参数用，见下） |
| `enabled` | 是否启用 |
| `rpm` | RPM 限额，`-` 表示不限 |
| `tok_used` | 已累计 Token 用量 |
| `tok_limit` | Token 软额度，`-` 表示不限 |
| `expires_at` / `last_used_at` | 过期时间 / 最近使用时间，`-` 表示无 |

`key list` 只显示打码前缀，**永远不会**显示完整 Key 或哈希。

> **实用提示：** 后续 `key disable` / `key enable` / `key set-limits`
> 及 `usage summary --key` 的参数是 **完整 Key 的前 12 个字符**
> （即 `emg_` 加后面 8 位，例如完整 Key 为 `emg_Ab1Cd2Ef3Gh4...` 时，
> 参数写 `emg_Ab1Cd2Ef3Gh4`），且必须唯一匹配。
> 展示用的打码形式 `emg_Ab1C****Gh4` 不能直接作为参数。
> 因此创建 Key 时建议连同前 12 字符一起记入密码管理器备注。

## 9. 调用 EasyModelGate

模型列表（需要携带用户 Key）：

```bash
curl -H "Authorization: Bearer <EMG_API_KEY>" \
  http://127.0.0.1:3000/v1/models
```

对话补全：

```bash
curl http://127.0.0.1:3000/v1/chat/completions \
  -H "Authorization: Bearer <EMG_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<MODEL_NAME>",
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'
```

流式：

```bash
curl -N http://127.0.0.1:3000/v1/chat/completions \
  -H "Authorization: Bearer <EMG_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<MODEL_NAME>",
    "stream": true,
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

`<MODEL_NAME>` 必须是上游后端实际暴露的模型名（可用 `/v1/models` 查看）。
网关对请求体和响应内容全部透传，不检查、不改写。

## 10. OpenCode 接入

编辑 OpenCode 配置文件 `~/.config/opencode/opencode.jsonc`，
增加一个 OpenAI-compatible provider：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "local-emg": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Local via EasyModelGate",
      "options": {
        "baseURL": "http://127.0.0.1:3000/v1",
        "apiKey": "<EMG_API_KEY>"
      },
      "models": {
        "<MODEL_NAME>": {}
      }
    }
  }
}
```

使用：

```bash
opencode run --model local-emg/<MODEL_NAME> "你好"
```

对比两种链路：

```
直连后端：      OpenCode → http://127.0.0.1:8080/v1        （无鉴权、无统计）
经网关：        OpenCode → http://127.0.0.1:3000/v1 → backend（鉴权、限流、用量统计）
```

建议保留原直连 provider 作为回滚通道：网关出问题时把 `--model` 前缀
换回直连 provider 即可，完全不依赖网关。

建议将 `opencode.jsonc` 权限设为 600（其中含有 API Key）。

## 11. 查看 Token 用量

最常用的几个查询：

```bash
# 今日总览
python -m easymodelgate --config configs/config.toml usage summary --period today

# 今日按小时
python -m easymodelgate --config configs/config.toml usage summary \
  --period today --group-by hour

# 本周按天 / 本月按天
python -m easymodelgate --config configs/config.toml usage summary --period week  --group-by day
python -m easymodelgate --config configs/config.toml usage summary --period month --group-by day

# 自定义范围（时间按配置时区理解）
python -m easymodelgate --config configs/config.toml usage summary \
  --from "2026-08-01 00:00" --to "2026-08-28 00:00" --group-by day
```

`--period` 可选值：`today`、`yesterday`、`24h`、`7d`、`week`、`month`、`all`。
`--group-by` 可选值：`hour`、`day`、`week`、`month`、`none`。
`--from` / `--to` 格式为 `"YYYY-MM-DD HH:MM"`。

输出每列的含义：

| 列 | 含义 |
|---|---|
| 请求数 / 成功 / 失败 | 请求总数与按状态码的成败计数 |
| prompt / completion / total | Token 用量（来自上游返回的 usage） |
| cached | 上游报告的 cached prompt tokens |
| 平均耗时ms | 网关视角的端到端耗时 |
| 平均排队ms / 最大排队ms | 等待后端 slot 的时间 |
| 平均upstream ms | 上游完整响应耗时 |
| 平均TTFT ms | 流式响应首字节时间 |

## 12. 按用户 / Key / 模型查询

```bash
# 按用户
python -m easymodelgate --config configs/config.toml usage summary --period week --user alice

# 按 Key（参数为完整 Key 的前 12 个字符，见第 8 节提示）
python -m easymodelgate --config configs/config.toml usage summary --period week --key emg_Ab1Cd2Ef3Gh4

# 按模型
python -m easymodelgate --config configs/config.toml usage summary --period week --model <MODEL_NAME>
```

`--user` 接受用户名；`--key` 接受 Key 前缀（必须唯一匹配到一个 Key）；
`--model` 接受完整模型名。三个过滤器可与 `--period` / `--from` / `--group-by` 组合。

## 13. RPM（每分钟请求限制）

RPM = Requests Per Minute。`--rpm 60` 表示该 Key 每分钟最多约 60 个请求。

超限返回：

- HTTP `429`，错误 `code` 为 `rate_limit_exceeded`
- 响应头带 `Retry-After`（秒），按其等待后重试即可

创建 Key 时设置：

```bash
python -m easymodelgate --config configs/config.toml key create --user alice --name laptop --rpm 60
```

修改已有 Key：

```bash
python -m easymodelgate --config configs/config.toml key set-limits emg_Ab1Cd2Ef3Gh4 --rpm 30
```

注意：RPM 是内存固定窗口计数，**网关重启后当前窗口清零**。

## 14. Token Quota（软额度）

Token Quota 是 **soft** 语义：

- 请求开始前 `used < limit` → 本请求放行并完整执行
- 即使完成后 `used > limit`，**也不会中断已放行的请求**
- 下一次请求开始前检查到 `used >= limit` 才拒绝

超限返回 HTTP `429`，错误 `code` 为 `insufficient_quota`。

设置 / 修改额度：

```bash
python -m easymodelgate --config configs/config.toml key set-limits emg_Ab1Cd2Ef3Gh4 --token-limit 5000000
```

查看已用量：`key list` 的 `tok_used` 列（仅当上游返回 usage 时才累计；
上游没返回 usage 的请求不估算、不扣减）。

清除额度（恢复不限）：

```bash
python -m easymodelgate --config configs/config.toml key set-limits emg_Ab1Cd2Ef3Gh4 --clear-token-limit
```

## 15. 修改 Key 限制速查

`key set-limits <12位前缀>` 支持四个参数，可任意组合：

```bash
# 改 RPM
... key set-limits emg_Ab1Cd2Ef3Gh4 --rpm 120

# 改 Token 额度
... key set-limits emg_Ab1Cd2Ef3Gh4 --token-limit 10000000

# 清除 RPM（恢复不限）
... key set-limits emg_Ab1Cd2Ef3Gh4 --clear-rpm

# 清除 Token 额度（恢复不限）
... key set-limits emg_Ab1Cd2Ef3Gh4 --clear-token-limit
```

## 16. 禁用 / 启用 Key

v0.1.0 没有删除 Key 的命令，只有停用与启用（按 12 位前缀）：

```bash
... key disable emg_Ab1Cd2Ef3Gh4   # 立即拒绝调用（401 key_disabled），历史记录保留
... key enable  emg_Ab1Cd2Ef3Gh4
```

这样设计是有意的：Key 记录保留后，历史 usage / request logs 仍能
关联到对应的 Key 与用户。**不建议、也无法直接删 Key 来抹记录。**

泄露应急：`key disable` 旧 Key → `key create` 新 Key → 更新客户端配置。

## 17. 查看服务是否正常

从外到内逐层排查：

```bash
# 1) 网关活着吗
curl http://127.0.0.1:3000/health
#    {"status":"ok","version":"0.1.0"}

# 2) 鉴权与上游连通吗（需要合法 emg_ Key）
curl -H "Authorization: Bearer <EMG_API_KEY>" http://127.0.0.1:3000/v1/models

# 3) 完整推理链路
curl http://127.0.0.1:3000/v1/chat/completions \
  -H "Authorization: Bearer <EMG_API_KEY>" -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","messages":[{"role":"user","content":"ping"}]}'

# 4) 上游本身
curl http://127.0.0.1:8080/health        # llama.cpp 自身健康检查

# 5) 数据库（CLI 统计异常时）
python -m easymodelgate --config configs/config.toml usage summary --period 24h
```

哪一步先失败，问题就在哪一层。

## 18. 常见错误

| 现象 | 常见原因 | 处理方式 |
|---|---|---|
| `401` `invalid_api_key` | 未带 Key / Key 错误 / Key 不属于本网关 | 检查 `Authorization: Bearer emg_...` 是否完整 |
| `401` `key_disabled` | Key 已被 disable | `key enable` 或换 Key |
| `401` `key_expired` | 超过 `--expires-in-days` 期限 | 重新创建 Key |
| `403` `user_disabled` | 所属用户被 disable | `user enable` |
| `429` `rate_limit_exceeded` | 触发 RPM 限流 | 按响应头 `Retry-After` 等待重试，或调大 `--rpm` |
| `429` `insufficient_quota` | Token 软额度用尽 | 调大 `--token-limit` 或 `--clear-token-limit` |
| `503` `server_busy` | 后端 slot 全被占用且排队超过 `queue_timeout` | 稍后重试；或调大 `upstream.slots` / `queue_timeout` |
| `504` `timeout` | 请求总时长超过 `timeouts.total_request` | 调大 `total_request`，或缩短提示词 |
| `502` `connection_error` | 上游没启动 / `upstream.base_url` 写错 | 先直接 `curl` 上游确认存活 |
| `ModuleNotFoundError: easymodelgate` | 未执行 `pip install -e .` | 见第 2 节 |
| 启动即退出：配置文件未找到 | 没复制 `configs/config.toml` 或 `--config` 路径错 | 见第 3 节（fail-fast 是设计行为） |
| 上游 401（网关日志/日志表中可见） | `upstream_key` 内容错或上游轮换过 Key | 更新 `configs/upstream_key` 后重启网关 |

## 19. 安全建议

永远不要提交到 Git（本仓库 `.gitignore` 已默认排除）：

```
configs/config.toml
configs/upstream_key
.env
data/
logs/
*.db / *.db-wal / *.db-shm
*.gguf
```

- 完整 `emg_` Key 只保存到密码管理器等安全位置；不要写进
  Git、README、截图、Issue 或任何日志
- 数据库只保存 Key 的 SHA-256 哈希与前 12 位前缀，完整 Key 泄露只能
  靠 disable 作废，无法从数据库反查——所以创建时的展示要妥善保管
- `configs/upstream_key`、`opencode.jsonc` 等含密钥文件 `chmod 600`
- 上游 Key 轮换：更新 `configs/upstream_key` 内容 → 重启网关

## 20. 日常管理速查表

以下命令中 `...` = `python -m easymodelgate --config configs/config.toml`。

| 任务 | 命令 |
|---|---|
| 创建用户 | `... user create --username alice --display-name "Alice"` |
| 列出用户 | `... user list` |
| 停用 / 启用用户 | `... user disable --username alice` / `... user enable --username alice` |
| 创建 Key | `... key create --user alice --name laptop --rpm 60` |
| 创建带额度 Key | `... key create --user alice --name opencode --rpm 60 --token-limit 5000000` |
| 列出 Key | `... key list [--user alice]` |
| 改 RPM | `... key set-limits <12位前缀> --rpm 30` |
| 改 Token 额度 | `... key set-limits <12位前缀> --token-limit 1000000` |
| 清除限额 | `... key set-limits <12位前缀> --clear-rpm --clear-token-limit` |
| 禁用 / 启用 Key | `... key disable <12位前缀>` / `... key enable <12位前缀>` |
| 今日用量 | `... usage summary --period today` |
| 按小时 | `... usage summary --period today --group-by hour` |
| 自定义范围 | `... usage summary --from "2026-08-01 00:00" --to "2026-08-28 00:00" --group-by day` |
| 按用户 / Key / 模型 | `... usage summary --period week --user alice`（`--key`、`--model` 同理） |
| 启动网关 | `... serve` |
| 健康检查 | `curl http://127.0.0.1:3000/health` |
