# Phase 14 部署报告：systemd 正式部署与部署文档

- 日期：2026-08-26
- 前置：Checkpoint 1/2/3 + Phase 12 + Phase 13 均 PASS
- 结论：**PHASE_14 = PASS**（含一项部署形态说明，见 §3/§19）

## 1. 部署目标

将前台临时启动转换为 systemd 长驻服务，完成部署文档、安全检查、生命周期验证、
OpenCode 部署后冒烟。零业务功能变更。

## 2. Unit 文件

- **当前生效**：用户级 `~/.config/systemd/user/easymodelgate.service`
  （原因见 §3），内容与文档 `docs/deployment/EasyModelGate-v0.1-Deployment.md §4` 一致。
- **系统级模板**已随部署文档提供（含 `Requires=llama-server.service` 与
  `RequiresMountsFor=<项目挂载点>`），供运维获得 sudo 后一次性升级安装。
- unit 内经扫描确认 **0 处密钥/Authorization/API_KEY**。

## 3. Python / 配置路径 与 部署形态说明

| 项 | 值 |
|---|---|
| 生产解释器 | `<HOME>/micromamba/envs/easymodelgate/bin/python`（realpath 指向 python3.12） |
| 版本 | Python 3.12.13；依赖全部命中冻结版本 |
| 配置 | WorkingDirectory=项目根 + `--config configs/config.toml` |

**部署形态说明**：本机 `sudo` 无免密授权且 `loginctl enable-linger` 需交互认证，
系统级安装无法在本阶段非交互完成。故采用**用户级 systemd 单元**等价部署：
本会话内 start/restart/stop/on-failure/journald 全部按 systemd 语义验证通过；
开机自启的最后一步为运维单命令 `sudo loginctl enable-linger <SERVER_USER>`
（系统级 unit 模板亦已备好）。该限制不涉及任何代码或协议行为。

## 4. 权限

upstream_key=600(<SERVER_USER>)；OpenCode 主配置与备份=600；data/logs 目录可写；
服务以 <SERVER_USER> 运行（非 root）；hardening 三项启用并实测无阻断。

## 5. 挂载盘检查

项目位于 `/dev/sdc`(ext4) 挂载点 `/media/<SERVER_USER>/<uuid>`：
- systemd 已存在对应 `.mount` unit（active）
- **未写入 /etc/fstab** → 重启后是否自动挂载不受本项目控制
- 已采取措施：配置/数据库均在挂载盘上，磁盘缺席时服务必然 fail-fast
  （BUG-P14 防护见 §16），不会带错误配置静默运行
- 文档已建议运维写入 fstab；届时系统级模板的 RequiresMountsFor 生效

## 6-8. systemd start / health / API 冒烟

- ExecStartPre 上游门控 exit 0 → MainPID 启动 → active(running)
- `ss`: :3000 由 python 监听 ✓
- `/health` → 200 {"status":"ok","version":"0.1.0"} ✓
- `/v1/models` 200；non-stream "OK"+tokens；stream [DONE]；
  tool_calls finish_reason=tool_calls args={"city":"北京"} ✓

## 9. OpenCode 冒烟（经 local-qwen-emg）

- 基础问答 rc=0："systemd deploy OK"
- 只读 Tool Calling rc=0：ls 列出 file_a/file_b
- 全链路 OpenCode → systemd 网关 → llama.cpp → Qwen 打通 ✅

## 10. restart 测试

restart 后 active、:3000 恢复、/health 200、SQLite 四表计数与 token_used
前后完全一致（users=2, keys=10, max_used=289571, logs=103）✅

## 11. stop/start 测试

stop 后 :3000 释放；journal 中 pending-task/unclosed 告警 **0 条**
（后台日志任务 flush 与 AsyncClient 关闭干净）；start 后恢复正常 ✅

## 12. on-failure restart

kill -9 主进程一次 → **3.6 秒后自动恢复**（RestartSec=3 语义吻合）、新 PID、
health 200 ✅

## 13. enable 状态

`systemctl --user is-enabled` = **enabled**（default.target.wants 已建立）。
llama-server.service 的 enable 状态未被触碰。
开机自启完整生效的前置条件（linger）见 §3 说明。

## 14. journald

`journalctl --user -u easymodelgate` 可查看启停与错误；本机 journald 为运行时
模式（重启即清空，属环境现状）。密钥扫描（upstream+emg 精确比对）**0 泄漏**。

## 15. SQLite persistence

见 §10；另验证 schema_version=1 保持、多次 restart 幂等。

## 16. 发现问题与最小修复

**ISSUE-P14-01（fail-fast 缺口，部署关键）**

- 现象：显式指定但不存在/不可读的 `--config` 路径会被静默忽略，
  服务回落默认值"正常"启动——违反任务书 §二十一。
- 根因：load_config 候选路径均缺失时未报错。
- 修复：候选全部缺失时抛 FileNotFoundError（仅 config.py 加载器，
  未触碰任何已冻结业务链路）。
- 回归测试：新增 tests/unit/test_config_failfast.py ×4
  （显式/env/默认三种缺失 + 正常加载）。
- 实机验证：unit 指向 NOT-EXIST.toml → 服务进入 activating/failed 循环，
  绝不进入 running；恢复后 active+health OK。

## 17. 全量自动测试

**118 passed / 0 failed**（114 + fail-fast 新增 4），~21s。

## 18. 安全终检

① unit 0 密钥 ② journal 0 密钥 ③ docs 0 密钥 ④ upstream_key=600
⑤ OpenCode 配置=600 ⑥ SQLite 无内容列 ⑦ 测试 Key 无泄漏
⑧ p13-rpm/p13-quota scratch keys 保持 disabled ✅ 全部通过。

## 19. 与冻结规格差异

1. 部署层级：规格示例为系统级 unit；因 sudo/linger 授权限制，
   本阶段落地为**用户级 unit + 运维交接命令**（§3），系统级模板已备好。
   功能语义（长驻/自愈/日志/hardening）完全一致。
2. journald 持久化依赖运维开启（环境现状，未引入 logrotate 等）。
3. 其余与 Phase 0–13 报告累积差异清单一致，无新增。

## 20. 风险

1. 服务器重启后：若挂载盘未自动挂载 → 服务 failed 循环（fail-fast，可见）；
   若挂载正常但 linger 未启用 → 服务不随开机启动，需手动 start（已文档化）。
   两者的运维交接命令均已写入部署文档。
2. 用户级 journal 非持久，跨重启历史不可查（可由运维开启持久 journal）。
3. Requires=llama-server 仅在系统级模板中体现；用户级以健康门控等效替代。

## 21. 最终结论

**PHASE_14 = PASS**

v0.1 全部阶段（Phase 0 → 14）闭环。最终拓扑：

```
OpenCode ──local-qwen──────────────────────► llama-server :8080 ──► Qwen3.8
        └─local-qwen-emg─► easymodelgate :3000 ─┘
                           （systemd 长驻 · Restart=on-failure · WAL 持久化）
```
