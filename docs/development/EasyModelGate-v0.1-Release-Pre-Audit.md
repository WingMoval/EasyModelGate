# EasyModelGate v0.1.0 GitHub 发布前审计

- 审计日期：2026-08-26
- 审计方式：**纯只读**（find/grep/du/ls/stat/ps/ss/git 只读/SQLite SELECT/pytest --collect-only）
- 审计范围：项目根目录全量 + micromamba 环境 + /tmp 残留 + OpenCode 配置关联面

---

## 1. 执行摘要

```
RELEASE_PRE_AUDIT = PASS_WITH_ACTIONS
```

结论：仓库资产完整、Secret 零泄漏、源码级零本机硬编码，**具备公开上传条件**；
但存在若干 P1/P2 整改项（Git 尚未初始化、config.toml 本地实配需确认不入库、
少量机器路径仅存在于部署文档属合理记录、README 可再补两节）。
均不构成 Blocker，详见 §15/§16。

## 2. 当前项目资产

| 资产 | 规模 | 内容 |
|---|---|---|
| easymodelgate/（产品源码） | 164K | app/cli/config + core/proxy/routers/services/db，结构完整 |
| tests/ | 152K | unit×6 文件、integration×12、fake_upstream×1；**pytest collected = 118** |
| experiments/phase-0.5/ | 244K | 5 个实验 RESULT+scripts+samples 齐备（见 §14） |
| docs/ | 216K | research/specifications/decisions/development/protocol/deployment 六类齐全 |
| configs/ | 16K | config.example.toml（模板）、config.toml（本地实配）、upstream_key(600) |
| data/ | 120K | 生产 SQLite（WAL 三件套）——运行数据 |
| logs/ | 44K | serve/perf 运行日志 —— 运行残留 |
| scripts/ | 16K | init_dev_env.sh、perf_check.py |
| 根文件 | — | README.md / LICENSE(Apache-2.0) / requirements.txt / environment.yml / pyproject.toml / .gitignore |

非缓存文件总数 113；服务当前由 systemd 用户单元以生产环境运行中。

## 3. 必须上传 GitHub（MUST_COMMIT）

- `easymodelgate/**`（全部产品源码与 db/schema.sql）
- `tests/**`（unit/integration/fake_upstream——正式工程资产）
- `scripts/init_dev_env.sh`、`scripts/perf_check.py`
- `README.md`、`LICENSE`、`requirements.txt`、`environment.yml`、`pyproject.toml`
- `configs/config.example.toml`
- `.gitignore`

## 4. 建议上传 GitHub（SHOULD_COMMIT）

- `docs/**` 全部（research/specifications/decisions/development/protocol/deployment）
- `experiments/phase-0.5/**`（RESULT/scripts/samples——已验证无 Secret，
  是架构决策的实证资产，**不得视为垃圾清理**）
- Phase 12 性能方法：`scripts/perf_check.py`（已在 MUST）+ `logs/perf_phase12.json`
  建议移入 docs 或保留于 logs 并忽略——二选一，人工定夺
- GitHub CI：当前不存在 → **待新增**（P2：pytest 自动化 workflow）

## 5. 禁止上传 GitHub（MUST_NOT_COMMIT）

| 路径 | 类型 | 处理 |
|---|---|---|
| `configs/upstream_key` | **REAL_SECRET**（llama.cpp key，53B，600） | 仅 .gitignore 已覆盖 ✓ |
| `configs/config.toml` | 本地实配（含 upstream_key 相对引用；无 Key 明文，实测命中 0） | 已覆盖 ✓ |
| `data/easymodelgate.db*` | 生产数据库（users/keys/usage 记录） | 已覆盖 ✓ |
| `logs/*.log` | 运行日志（serve-p12/p13 等） | 已覆盖 ✓ |

OpenCode 私有配置及 phase13 备份均在 `~/.config/opencode/`（仓库外）✓；
仓库内未发现 *.bak/.env/OpenCode 配置副本。

## 6. 可清理运行残留（只列不删）

| 对象 | 量级 | 说明 |
|---|---|---|
| `__pycache__/`(10 目录,43 pyc) + `.pytest_cache/` | ≈628KB | 安全清理候选 |
| micromamba env `easymodelgate-test` | 266MB（py3.12.13） | Phase 0.5 实验环境，可清理候选；dev/production 必须保留 |
| `/tmp/emg-exp03-dir`、`/tmp/emg-exp05-*` | 各 12K | 实验临时目录，无进程占用 |
| `/tmp/easymodelgate-phase13/`（含 agent-ws/big.txt） | 136K | A/B 测试工作区，无长期价值 |
| `/tmp/opencode/` | 268K | 调试输出（含历史 json/sse），无进程占用 |
| `logs/serve-smoke*.log`、`serve-cp2/cp3.log` | <20K | 阶段冒烟残留，可归档或删除 |
| `data/` 中 scratch Keys：cp2-spot、slot-check、perf、rpm-test、p13-quota(×2,disabled) | — | 审计证据，去留由人工决定 |

## 7. 需要人工确认的项目

1. `easymodelgate-test` 环境（266MB）是否删除。
2. `logs/perf_phase12.json` 归档位置（docs 还是随 logs 忽略）。
3. 数据库内 10 条 Key 记录的去留（尤其 alice 名下 4 把开发期 Key 与 2 把 disabled quota Key）。
4. 是否在发布前新增 GitHub Actions CI（P2）。
5. Git 初始化时机与首次 commit 信息（本阶段禁止执行）。
6. `/tmp/*` 清理时机（当前均无进程占用）。

## 8. Secret / 隐私审计

精确比对法（upstream key + emg 测试 key 全文匹配）+ 泛化模式扫描
（PRIVATE KEY BLOCK / password=）结果：

- upstream key：**仅存在于 `configs/upstream_key` 自身**（预期位置，600），
  其余全项目 0 命中 ✅
- emg 测试 Key（opencode.jsonc 内真实值）：项目内 **0 命中** ✅
  （该值实际存放点为仓库外的 OpenCode 私有配置，权限 600 ✓）
- `configs/config.toml` 不含 Key 明文（命中 0）✅
- 无 PRIVATE KEY 块、无 password 类赋值（tests 除外已豁免）✅
- 无 *.bak / .env 入库 ✅
- `data/easymodelgate.db`：request_logs **结构级无内容列**（PRAGMA 验证 PASS）；
  api_keys.key_hash 全为 64 位 hex（10/10），无明文形态 ✅

**结论：Secret/隐私维度干净。**

## 9. Git 历史安全审计

`.git` 不存在 → **Git repository not initialized**，无历史泄漏风险面。
（后续 git init 后首提交前，务必复核 §5 清单已被 .gitignore 生效拦截；
本阶段未执行任何 git 写操作。）

## 10. 本机硬编码审计

| 类别 | 出现位置 | 影响迁移？ | 建议 |
|---|---|---|---|
| /home/<SERVER_USER>（micromamba 绝对路径） | scripts/perf_check.py:17；deployment/spec 文档 | perf 脚本 MAJOR（他机需改路径）；文档 MINOR（部署记录性质） | P2：perf 改读环境变量；文档标注"示例路径" |
| /media/<SERVER_USER>/<uuid>（项目根/挂载点） | deployment 文档、spec | 文档 MINOR | 同上 |
| <SERVER_HOSTNAME> / User=<SERVER_USER> | deployment 文档 | MINOR | 同上 |
| 127.0.0.1:8080/:3000 | config.example(默认值 NONE)、源码 config.py 默认值(NONE)、tests(fake)、README/docs(说明) | **NONE**——均为合理默认/测试用途 | 保持 |
| qwen3.8-local | fake_upserver 常量、perf 脚本 | MINOR（fake 测试模型名，非代码依赖） | 保持 |

**核心结论：`easymodelgate/` 产品源码 0 处本机硬编码**；所有机器相关内容
集中于部署文档（合理）与 perf 辅助脚本（P2 可配置化）。

## 11. 配置可迁移性

| # | 问题 | 结论 | 等级 |
|---|---|---|---|
| 1 | 免改源码、仅改配置可运行？ | 是（dict 透传 + TOML/env 双通道） | NONE |
| 2 | upstream URL 配置化？ | `[upstream].base_url` ✓ | NONE |
| 3 | DB 路径配置化？ | `[database].path` ✓ | NONE |
| 4 | host/port 配置化？ | `[server]` + EMG_SERVER_* ✓ | NONE |
| 5 | timezone 配置化？ | `[usage].timezone`（zoneinfo）✓ | NONE |
| 6 | upstream key 支持 env/file？ | env > file 双通道 ✓ | NONE |
| 7 | 依赖当前用户名？ | 否（源码零出现） | NONE |
| 8 | 依赖当前绝对路径？ | 否（相对路径基于 WorkingDirectory/cwd） | NONE |
| 9 | 依赖当前 GPU？ | 否 | NONE |
| 10 | 依赖 Qwen 名称？ | 否（model 字段纯透传；example 中的名字仅为示例值） | NONE |

## 12. systemd 可迁移性

当前 `~/.config/systemd/user/easymodelgate.service` 属**本机实际部署配置**
（WorkingDirectory/ExecStart 含机器路径；ExecStartPre 门控 llama :8080）。

建议发布时新增（P1）：

- `deploy/easymodelgate.service.example`：占位符版本
  （`{{PROJECT_ROOT}}`、`{{PYTHON_BIN}}`），并附系统级模板双形态；
- 可选 `deploy/install.sh` 生成脚本（读取交互输入渲染占位符）。

部署文档中的真实路径段落保留（属"当前服务器部署记录"，与模板互补）。

## 13. README 发布准备度

已有（适合陌生人）：简介定位、目标链路图、当前状态表（Phase1-14）、快速启动
（环境→配置→Key→serve→curl）、配置表、API 表、CLI、设计边界四条、安全原则、
开发状态、文档索引、License。

缺口（P2，不影响发布但建议补）：

1. 缺独立「项目简介」标题节与「系统要求」（Python3.12/micromamba/llama-server）小节；
2. 缺「测试」章节（如何跑 118 项 pytest）；
3. 缺「已知限制」小节（models 不限流等四条虽在「设计边界」，措辞可再显式）;
4. 版本号仅在 health 示例中出现，建议顶部徽标/文字注明 v0.1.0。

过时内容/开发措辞/机器专用内容：**未发现**。

## 14. 测试资产状态

- pytest collected：**118**（与本阶段基线一致）
- unit 6 文件 / integration 12 文件 / fake_upstream server.py 1 个（可编程剧本：
  SSE 分片、多事件合块、静默上游、中断、错误码矩阵、自定义 usage）
- Phase 0.5 五实验 RESULT+脚本+样本 **全部完整**（exp01×4、exp02×6、exp03×2、
  exp04×1、exp05×1 件产物），protocol 归档副本在 docs/protocol/llamacpp/

**强调：tests / experiments / protocol evidence 为正式工程与设计证据资产，
不得作为垃圾清理。**

## 15. Release Blockers

**无。** 未发现任何阻止公开上传的问题
（Secret 干净、无 Git 历史、源码无机器硬编码、隐私 schema 达标）。

## 16. Release Actions

- **P0**（发布前必须）
  - P0-1 `git init` 后按 §3/§5 清单执行首次提交前复核
    （`git status` 确认 MUST_NOT_COMMIT 四项全部被忽略）。
- **P1**（强烈建议同批完成）
  - P1-1 新增 `deploy/easymodelgate.service.example`（占位符双模板）。
  - P1-2 README 补「系统要求」「测试」「已知限制」三小节 + v0.1.0 标注。
- **P2**（可发布后跟进）
  - P2-1 perf_check.py 的 OPCODE_CFG/MODEL 改环境变量化。
  - P2-2 GitHub Actions：pytest 工作流。
  - P2-3 部署文档机器路径处追加"示例"措辞。
  - P2-4 决定 §7 人工确认六项并择机清理。

## 17. 本阶段修改

除新增本报告
`docs/development/EasyModelGate-v0.1-Release-Pre-Audit.md` 外，
**未修改任何源码、配置、环境、systemd、数据库、Git 状态**；
未删除任何文件；未执行 git init/add/commit/push。
