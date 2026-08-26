# EasyModelGate v0.1.0 Final Release Audit

- 审计日期：2026-08-26
- 前置：Pre-Audit PASS_WITH_ACTIONS → Stage 1 PASS → Stage 2 PASS
- 冻结候选：**120 个文件**（pre-publication hygiene 后实测）（清单：`docs/development/EasyModelGate-v0.1-Release-File-Manifest.txt`）

## 1. Executive Summary

```
FINAL_RELEASE_AUDIT   = PASS
READY_FOR_FIRST_COMMIT = YES
```

全部强制检查项通过：Secret / Privacy / Version / License / README /
CHANGELOG / Release Notes / CI / Packaging / 118 项最终回归 / Portability。
Git 处于 main 分支 0 commit、staged=0 的冻结状态，等待人工授权执行首次提交。

## 2. Release Candidate 文件清单

冻结清单文件：`EasyModelGate-v0.1-Release-File-Manifest.txt`（每行一相对路径）。

| 分类 | 数量 |
|---|---|
| SOURCE（easymodelgate/） | 26 |
| TEST（tests/） | **20** |
| EXPERIMENT（experiments/phase-0.5） | 31 |
| DOC（docs/ 含 protocol/releases/development/development 报告与清单） | 29 |
| DEPLOY（deploy/ 模板+说明） | 3 |
| CI（.github/workflows/tests.yml） | 1 |
| configs/config.example.toml | 1 |
| scripts/（init_dev_env.sh、perf_check.py） | 2 |
| 根级（README / LICENSE / CHANGELOG / requirements / environment.yml / pyproject / .gitignore / Manifest / 本审计报告） | 8 |
| **TOTAL** | **122**（含本审计报告与 Manifest 自身） |

正式发布前根据独立 Windows Release Audit，移除两个无价值实验日志，并将实验 OpenCode 配置路径改为用户目录/环境变量可覆盖形式；未改变核心产品逻辑。

排除验证：configs/config.toml、configs/upstream_key、data/**、logs/**、
缓存类 **0 个进入候选** ✅。tests/experiments/docs/protocol 属正式 Release 资产。

## 3. Secret Audit

对冻结 121 文件逐一扫描：

- upstream key 精确比对：0 命中
- emg 测试 key 精确比对：0 命中
- 泛化模式（PRIVATE KEY / password= / 长 Bearer）：tests 豁免假值外 0 命中

```
FINAL_TRACKED_SECRET_SCAN = PASS
```

## 4. Privacy Audit

- request_logs 表结构无 prompt/response/reasoning/tool arguments 列（PRAGMA 验证）
- SQLite(db/-wal/-shm)、OpenCode 私有配置、upstream_key 均被 .gitignore 排除，
  `git check-ignore -v` 权威确认 ✅
- docs / experiments / protocol samples 复核：仅含协议结构与脱敏样本，
  无真实聊天内容、真实 Key 或 Authorization ✅

```
FINAL_PRIVACY_CHECK = PASS
```

## 5. Version Check

pyproject.toml / easymodelgate.__version__ / README 顶部 / 部署文档 /
CHANGELOG [0.1.0] / Release Notes v0.1.0 全部一致；
预定 tag 名：`v0.1.0`。

```
VERSION_CHECK = PASS
```

## 6. License Check

- LICENSE：Apache License 2.0（官方全文）✅
- pyproject：`license = { text = "Apache-2.0" }` ✅
- 直接依赖实测 License-Expression：

| 包 | 版本 | 许可 |
|---|---|---|
| fastapi | 0.141.1 | MIT |
| starlette | 1.6.0 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| uvicorn | 0.52.4 | BSD-3-Clause |
| aiosqlite | 0.22.1 | MIT |
| pydantic | 2.13.4 | MIT |
| pytest | 9.1.1 | MIT |
| pytest-asyncio | 1.4.0 | Apache-2.0 |

全部为宽松许可，与 Apache-2.0 发布无冲突 ✅
AGPL 项目（new-api / croit）：源码与 tests 中关键词 **0 命中**；
仅在 Phase 0 研究文档与冻结规格中出现"研究引用"语境 ✅

```
LICENSE_CHECK = PASS
```

## 7. README Check

必需节齐全：名称+版本(v0.1.0)/简介/架构链路/核心功能(透明代理清单)/系统要求/
快速开始(git clone→env→pip→config→key→serve→curl)/配置表/API/CLI/OpenCode 接入
(双 Provider 回滚)/测试(118, fake upstream 无 GPU)/设计边界/安全原则/已知限制/
文档索引/License。

禁用措辞（待开发/尚未完成/待审核/TODO/过期 Checkpoint 指令）：**0 命中** ✅
过度承诺（全 backend 兼容/Windows/macOS/HA/多机/Dashboard 已支持）：**0 命中** ✅
兼容范围明确：Linux + Python 3.12 + llama.cpp OpenAI-compatible API ✅

## 8. CHANGELOG

新增 `CHANGELOG.md`：[0.1.0]-2026-08-26，Added/Known Limitations 两段式，
不含 Phase 过程叙事（历史保留于 docs/development）✅

## 9. Release Notes

新增 `docs/releases/EasyModelGate-v0.1.0-Release-Notes.md`：
面向 GitHub Release 页面的中文说明（是什么/核心能力/Validation 七项/
Supported Environment/Known Limitations/Documentation/License）。
无服务器用户名、磁盘 UUID、真实 IP、真实 Key、私有路径 ✅

## 10. GitHub Actions

`.github/workflows/tests.yml` 经 PyYAML 解析 + 内容检查：
checkout@v4 / setup-python@3.12 / pip install -r requirements.txt / pytest -q；
无 Secret、无机器路径、无 GPU 要求、无生产 upstream ✅

```
CI_STATIC_CHECK = PASS
CI_EXPECTED_TEST_COUNT = 118
```

## 11. Packaging

`pip install -e .`（release-test 环境）成功；项目外 `import easymodelgate`
得 0.1.0；console script 可用；验证后已卸载并清理构建残留。
发布包不包含 upstream_key / 生产 DB / logs（.gitignore + §2 排除验证）。
未引入 PyPI 发布流程（按范围仅针对 GitHub v0.1.0）✅

## 12. Final Test Result

easymodelgate-release-test 环境 × 项目根：

```
collected=118  passed=118  failed=0  warnings=1(第三方)  duration≈21.8s
```

## 13. Portability

对 easymodelgate/ scripts/ config.example deploy/ .github/ README CHANGELOG
docs/releases/ 扫描四类机器标识：**0 命中**。
历史 development/research/experiments 记录按要求豁免。

```
FINAL_PORTABILITY_CHECK = PASS
```

## 14. Git Status（终态）

| 项 | 值 |
|---|---|
| branch | main |
| commit | 0 |
| remote | 0 |
| tag | 0 |
| staged | 0 |
| ignored 条目 | data/ logs/ upstream_key config.toml 等（check-ignore 全命中） |

## 15. Known Limitations

见 README「已知限制」/ CHANGELOG 同名段：llama.cpp 单后端正式验证、
单实例内存 RPM 重启清零、软额度语义、models 不计限流、无 Admin API/Web、无 HA。

## 16. Remaining Operations（服务器运维事项 · 非 Release blocker）

1. upstream key 轮换（RECOMMEND_ROTATE_BEFORE_PUBLIC_RELEASE = YES，
   涉及共享 GPU 服务需人工授权）
2. `sudo loginctl enable-linger <SERVER_USER>`（开机自启最后一步）
3. `/dev/sdc` 挂载盘写入 fstab（消除重启后挂载不确定性）
4. scratch 测试 Keys 与 /tmp 残留的服务器侧 housekeeping

以上均为本机运维事项，与公开仓库内容无关。

## 17. Final Release Decision

所有强制项：

FINAL_TRACKED_SECRET_SCAN=PASS · FINAL_PRIVACY_CHECK=PASS · VERSION_CHECK=PASS ·
LICENSE_CHECK=PASS · CI_STATIC_CHECK=PASS · FINAL_PORTABILITY_CHECK=PASS ·
118/118 全绿

```
READY_FOR_FIRST_COMMIT = YES
```

建议首次提交命令（供人工审核后执行）：

```bash
cd <项目根>
git add .
git status --short            # 最终目测复核（应 121 项）
git commit -m "feat: EasyModelGate v0.1.0 — lightweight local model API gateway"
git tag -a v0.1.0 -m "EasyModelGate v0.1.0"
# remote/push 由维护者决定后另行执行
```
