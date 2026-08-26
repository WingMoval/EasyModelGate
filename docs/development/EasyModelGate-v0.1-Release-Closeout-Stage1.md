# EasyModelGate v0.1.0 Release Closeout — Stage 1（P0 安全收口 + P1 可迁移性整改）

- 日期：2026-08-26
- 前置：Release-Pre-Audit = PASS_WITH_ACTIONS
- 结论：**RELEASE_CLOSEOUT_STAGE1 = PASS**

## 1. 本阶段目标

GitHub 发布定稿第一部分：安全边界收口、Git 初始化（不 commit）、systemd 通用模板、
README 首发整理、辅助脚本去机器绑定、文档发布级修正、版本一致性与全量回归。
零业务功能变更，未触碰 Proxy/SSE/Auth/Quota/Analytics 与 schema v1。

## 2. .gitignore 修改

在原基础上新增：`.env` / `.env.*` / `*.bak` / `*.backup` / `*.py[cod]` /
`.coverage` / `htmlcov/` / `venv/` / `.idea/` / `.vscode/` / `.DS_Store`。
未忽略任何正式资产（tests/experiments/docs/scripts/config.example 均可入库，
已用 `git add --dry-run` 逐项抽验确认）。

## 3. Git 初始化结果

- 系统 git 为 **2.7.4**（不支持 `init -b main`）→ 采用 `git init` +
  `git symbolic-ref HEAD refs/heads/main` 等效设置默认分支。
- **未执行任何 commit**；HEAD 指向 refs/heads/main。

## 4. 首次 commit 候选检查

- `git status --short --ignored`：data/ 与 logs/ 显示为 `!!` ignored；
- `git check-ignore -v` 权威验证五项全部命中规则：
  upstream_key(第7行规则) / config.toml(8) / db(2 data/) / logs(3)；
- `git add --dry-run .`：精确候选 **115 个文件**
  （含 tests 20、experiments 33、docs 24、deploy 3、config.example/LICENSE/
  requirements/environment.yml/pyproject/README 等），候选中
  **0 个**敏感/运行/cache 文件。

## 5. Secret 二次扫描

针对 115 个候选文件逐一扫描（upstream key 与 emg 测试 key 精确比对 +
PRIVATE KEY / password= / 长 Bearer 泛化模式，tests 目录豁免假值）：

```
SECRET_SCAN_TRACKED_FILES = PASS
```

## 6. systemd 通用模板

新增：

- `deploy/easymodelgate-user.service.example`
  （占位符 {{PROJECT_ROOT}}/{{PYTHON_BIN}}/{{UPSTREAM_HEALTH_URL}}；
  含 ExecStartPre 上游健康门控与低风险加固三项）
- `deploy/easymodelgate-system.service.example`
  （另含 User={{RUN_USER}} / Requires={{UPSTREAM_SYSTEMD_SERVICE}} /
  RequiresMountsFor={{PROJECT_MOUNT_PATH}}，并在文件头注释明确"需自行替换、
  占位符非作者服务器路径"）
- 生产实际运行的 `~/.config/systemd/user/easymodelgate.service` **未做任何修改**。

## 7. README 修改

- 顶部标注 **EasyModelGate v0.1.0**
- 新增章节：**项目简介 / 系统要求 / 测试 / 已知限制**
- 快速开始补 `git clone` 步骤（无机器绝对路径）
- 修正过时状态句：「进入 Phase 8+ 前需通过 Checkpoint 审核。」
  →「Phase 8 及以后各阶段均已通过对应 Checkpoint 审核。」
- 未重写其它既有内容；历史开发报告一律未动。

## 8. perf 脚本迁移整改

`scripts/perf_check.py`：
- 删除硬编码 `<OPENCODE_CONFIG>` 及其死代码
  load()/up_cfg；
- 新增 `EMG_PERF_MODEL` / `EMG_PERF_RUNS` / `EMG_UPSTREAM_KEY_FILE`
  环境变量覆盖（默认值不含机器信息）；
- 性能测量逻辑未变。`py_compile` 通过；grep 复核 0 机器绑定。

## 9. 文档修正

`docs/deployment/EasyModelGate-v0.1-Deployment.md`：
- 顶部新增实例声明（用户名/路径/UUID 为作者服务器实例值，
  通用部署使用 deploy/*.example）；真实路径作为部署记录保留；
- 修正拼写：owner=<SERVER_USER_TYPO> → owner=<SERVER_USER>。

## 10. 版本一致性

pyproject.toml / easymodelgate/__init__.py / README 顶部 / deployment 文档
均为 **0.1.0** ✅（/health 由 __version__ 派生，自动一致）。

## 11. 测试结果

清理项目内缓存后全量回归（easymodelgate-dev 环境）：
**118 passed / 0 failed**（collected 数量与基线一致，无变化需解释）。

## 12. 迁移性复核

对发布候选范围 `easymodelgate/ scripts/ configs/config.example.toml deploy/`
重新扫描 `/home/<SERVER_USER>`、`/media/<SERVER_USER>`、`<MOUNT_UUID>`、`<SERVER_HOSTNAME>`：
文本文件 **0 命中**（仅 pytest 后重建的 .pyc 二进制残留含旧路径，
已再次清理并确认被 .gitignore 排除）。

```
PORTABILITY_STATIC_CHECK = PASS
```

## 13. Git status（当前快照）

- 分支：refs/heads/main（无 commit）
- untracked 候选 115 个文件（-uall 口径），MUST_NOT_COMMIT 全部 ignored
- 无 remote、无 tag、无 staged 文件

## 14. 当前 Release 风险

1. 开机自启依赖运维执行 `sudo loginctl enable-linger <SERVER_USER>`
   （用户级方案遗留项，命令已写入部署文档）。
2. 挂载盘未入 fstab：重启后若盘未挂载，服务将 failed 循环（fail-fast 可见），
   建议运维窗口处理。
3. upstream key 仍为开发期间同一把（见 §5 P0-5 建议）。

## 15. 下一步建议

人工审核本报告后，按序执行：
① 运维侧 rotate upstream key 并同步 configs/upstream_key → 重启服务；
② `sudo loginctl enable-linger <SERVER_USER>`；
③ 首次 commit（建议拆分：源码+测试+文档 单 commit 或按目录分批）；
④ 创建 GitHub 远端与 v0.1.0 tag/Release；
⑤ P2 事项（GitHub Actions CI、/tmp 与 scratch Key 清理）可在发布后跟进。

## 附：P0-5 upstream Key 轮换建议

当前 `configs/upstream_key` 内容与开发期首次创建时相同（mtime 2026-08-26 01:57，
即开发首日生成后从未更换）：

```
RECOMMEND_ROTATE_BEFORE_PUBLIC_RELEASE = YES
```

轮换属 llama.cpp 侧操作（--api-key-file 更换 + 同步本文件 + 重启上游），
涉及共享 GPU 服务，须人工授权后另行执行；本项目侧仅需更新该文件内容并重启网关。
