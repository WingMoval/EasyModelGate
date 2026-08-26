# EasyModelGate v0.1 部署文档

> 适用版本：v0.1.0 · 更新日期：2026-08-26 · 部署形态：systemd（用户级）长驻服务
>
> **说明**：本文件是作者当前服务器的**实际部署实例记录**，其中的用户名
> （<SERVER_USER>）、绝对路径与挂载 UUID 均为实例值。通用部署请使用仓库中的
> `deploy/*.service.example` 模板与 `deploy/README.md` 说明，按自身环境填写。

## 1. 部署环境

| 项 | 值 |
|---|---|
| 主机 | <SERVER_HOSTNAME>（Ubuntu 16.04.7 / 内核 4.15 / glibc 2.31） |
| 运行用户 | <SERVER_USER>（非 root） |
| 上游 | llama-server.service（Qwen3.8-27B，ctx=32768，--parallel 1）@ 127.0.0.1:8080 |
| 项目根 | `<PROJECT_ROOT>` |

## 2. Python 环境

- 环境管理：micromamba，**生产环境名 `easymodelgate`**
- 解释器绝对路径：
  `<HOME>/micromamba/envs/easymodelgate/bin/python`（Python 3.12.13）
- 依赖冻结见 `requirements.txt`（fastapi==0.141.1 等 8 项）
- systemd **直接调用该绝对路径**，禁止 `source activate` / `bash -lc`

重建环境：

```bash
micromamba create -y -n easymodelgate python=3.12.13
PIP_CONFIG_FILE=/dev/null $HOME/micromamba/envs/easymodelgate/bin/pip \
    install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

（`PIP_CONFIG_FILE=/dev/null` 用于绕过全局 pip 配置中已失效的 nvidia extra-index。）

## 3. 配置文件与 Secret 管理

| 文件 | 说明 | 权限 |
|---|---|---|
| `configs/config.toml` | 实际配置（由 config.example.toml 复制修改） | 664 |
| `configs/upstream_key` | llama.cpp API Key 明文 | **600，owner=<SERVER_USER>** |
| `data/easymodelgate.db` | SQLite（WAL） | 服务自动创建 |

- upstream key 优先级：环境变量 `EMG_UPSTREAM_API_KEY` > `configs/upstream_key`
- **unit 文件与环境变量中不写任何真实 Key**

## 4. systemd Unit（当前生效：用户级）

路径：`~/.config/systemd/user/easymodelgate.service`

```ini
[Unit]
Description=EasyModelGate Lightweight Local Model API Gateway
After=default.target

[Service]
Type=simple
WorkingDirectory=<PROJECT_ROOT>
ExecStartPre=/bin/sh -c 'i=0; until curl -sf -m 2 http://127.0.0.1:8080/health >/dev/null 2>&1; do i=$((i+1)); [ $i -gt 60 ] && { echo "upstream llama-server :8080 未就绪"; exit 1; }; sleep 2; done'
ExecStart=<HOME>/micromamba/envs/easymodelgate/bin/python -m easymodelgate --config configs/config.toml serve
Restart=on-failure
RestartSec=3
TimeoutStopSec=15
KillSignal=SIGTERM
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false

[Install]
WantedBy=default.target
```

要点：

1. 用户级 unit 无法直接 `Requires=llama-server.service`（跨层级不可见），
   以 **ExecStartPre 健康门控**（最长等 120s）实现"上游就绪后再启动"。
2. 项目位于 `/dev/sdc` 挂载盘且**未写入 /etc/fstab**：若重启后磁盘未挂载，
   配置读取将失败 → 服务进入 failed/restart 循环（fail-fast，不会带错误配置运行）。
   建议运维在维护窗口将该盘写入 fstab；届时系统级部署可追加
   `RequiresMountsFor=/media/<SERVER_USER>/<MOUNT_UUID>`。
3. Hardening 仅采用低风险三项（NoNewPrivileges/PrivateTmp/ProtectSystem=full），
   已实测不阻断项目目录、SQLite、micromamba 环境访问。

### 系统级 Unit 模板（供运维后续升级，需 sudo）

```ini
[Unit]
Description=EasyModelGate Lightweight Local Model API Gateway
After=network-online.target llama-server.service
Requires=llama-server.service
RequiresMountsFor=/media/<SERVER_USER>/<MOUNT_UUID>

[Service]
Type=simple
User=<SERVER_USER>
WorkingDirectory=<PROJECT_ROOT>
ExecStart=<HOME>/micromamba/envs/easymodelgate/bin/python -m easymodelgate --config configs/config.toml serve
Restart=on-failure
RestartSec=3
TimeoutStopSec=15
KillSignal=SIGTERM
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false

[Install]
WantedBy=multi-user.target
```

安装命令（需 sudo）：

```bash
sudo cp <unit> /etc/systemd/system/easymodelgate.service
sudo systemctl daemon-reload
sudo systemctl enable --now easymodelgate.service
sudo loginctl enable-linger <SERVER_USER>   # 若继续使用用户级方案则执行此条即可
```

## 5. 启动 / 停止 / 重启 / 状态

```bash
systemctl --user start    easymodelgate
systemctl --user stop     easymodelgate
systemctl --user restart  easymodelgate
systemctl --user status   easymodelgate
systemctl --user is-enabled easymodelgate   # 开机自启（需配合 linger，见 §6）
```

## 6. 开机自启（重要说明）

- 当前已执行 `systemctl --user enable`（default.target.wants 已建立）。
- 但用户级管理器随登录/linger 启动；本机当前 `Linger=no` 且启用需要交互授权。
- **运维交接一条命令**（任意一次获得 sudo 的窗口执行）：

```bash
sudo loginctl enable-linger <SERVER_USER>
```

执行后无需登录，开机即由 user manager 自动拉起本服务。
在此之前，服务器重启后需手动执行 `systemctl --user start easymodelgate`。

## 7. 日志查看

```bash
journalctl --user -u easymodelgate -f          # 跟随
journalctl --user -u easymodelgate --since today
```

- 本机 journald 为运行时（非持久）模式：机器重启后历史日志清空；
  如需持久化可由运维启用 `/var/log/journal`（超出 v0.1 范围）。
- 日志内容保证不含：upstream/emg Key、Authorization、prompt/response、tool arguments。

## 8. 健康检查

```bash
curl http://127.0.0.1:3000/health
# {"status":"ok","version":"0.1.0"}
```

## 9. OpenCode 接入方式

`~/.config/opencode/opencode.jsonc`（600）中保留双 Provider：

| Provider | baseURL | 说明 |
|---|---|---|
| local-qwen | http://127.0.0.1:8080/v1 | 直连 llama.cpp（回滚通道） |
| local-qwen-emg | http://127.0.0.1:3000/v1 | 经 EasyModelGate |

使用：`opencode run --model local-qwen-emg/qwen3.8-local "..."`
回滚：改用 `local-qwen/qwen3.8-local` 即可，完全不依赖网关。

## 10. 常见错误

| 现象 | 原因/处理 |
|---|---|
| 启动失败：配置文件未找到 | 未创建 configs/config.toml 或路径错误（fail-fast 设计） |
| ExecStartPre 报 upstream 未就绪 | llama-server 未运行/未监听 8080 |
| 503 server_busy | 全部 slot 被占用超过 queue_timeout，稍后重试 |
| 429 rate_limit_exceeded | 触发 RPM，按 Retry-After 重试 |
| 429 insufficient_quota | token_used ≥ token_limit（软额度），调大限额 |
| journal 为空/重启后清空 | 运行时 journal，属预期；持久化见 §7 |

## 11. 数据库位置与备份建议

- 数据库：`data/easymodelgate.db`（WAL，含 -wal/-shm 辅助文件）
- 备份（建议每日）：

```bash
sqlite3 data/easymodelgate.db ".backup backup/easymodelgate-$(date +%F).db"
```

- 同时备份 `configs/config.toml`；`configs/upstream_key` 泄露时轮换：
  更新文件内容后 `systemctl --user restart easymodelgate`。

## 12. 升级流程

```bash
systemctl --user stop easymodelgate
cp data/easymodelgate.db backup/ && cp configs/config.toml backup/
# 更新代码（git pull / 同步），如依赖变化仅允许使用冻结版本清单重装
$HOME/micromamba/envs/easymodelgate-dev/bin/python -m pytest -q   # 118 项全绿
systemctl --user start easymodelgate
curl http://127.0.0.1:3000/health
```

## 13. 回滚流程

1. **客户端即时回滚**（零依赖）：OpenCode 切换 Provider 至
   `local-qwen/qwen3.8-local`，流量直达 llama.cpp。
2. 代码回滚：恢复上一版本目录/提交后 `systemctl --user restart easymodelgate`。
3. 数据回滚：用 §11 备份覆盖 db 前先 stop 服务。

## 14. 安全注意事项

- 服务以 <SERVER_USER> 运行，禁止 root；unit 内无任何真实密钥。
- `configs/upstream_key` 与 OpenCode 配置保持 600。
- 日志脱敏为代码层保证（Phase 12 安全扫描基线）。
- 升级或轮换密钥后务必执行安全扫描脚本流程（精确比对法）。
