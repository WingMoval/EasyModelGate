# EasyModelGate v0.1.0 Final Privacy Sanitization Report

- 阶段：Stage 4B-R2 — Final Privacy Sanitization + Local History Rewrite
- 日期：2026-08-27
- 版本：v0.1.0（正式 tag 尚未创建）

## 1. Background

Stage 4B-R1 之后的 Windows clean-clone 独立复审结论为 PASS（无 blocker），
但仍发现若干 non-blocking 的机器身份信息引用（machine identity references）：
历史 docs 中残留真实服务器用户名、主机名、个人用户名路径段、磁盘挂载 UUID
及真实绝对路径。

由于正式 v0.1.0 tag / GitHub Release 尚未创建、GitHub 远端当前为空仓库，
经人工批准，在正式发布前执行最后一次公开仓库隐私脱敏与本地 Git 历史重建。

因当前环境缺少 git-filter-repo（且明确禁止安装新工具、禁止使用
git filter-branch、禁止修改系统 Git），本轮经人工确认采用
**Clean History Reconstruction**：以脱敏后的各 commit 内容快照重新构造
全新的本地 Git 历史，旧历史整体废弃、仅存项目外 bundle。

## 2. Sanitized Information

本轮从全部公开内容与全部新历史中清除、并统一替换为以下占位符的信息类型：

- `<SERVER_USER>` — 真实服务器运行用户名
- `<SERVER_HOSTNAME>` — 真实服务器主机名
- `<PROJECT_USER>` — 真实个人/项目用户名路径段
- `<MOUNT_UUID>` — 真实磁盘挂载 UUID（含其短前缀）
- `<PROJECT_ROOT>` — 真实项目绝对路径（完整项目根）
- `<AI_ROOT>` — 真实 AI 工作区根目录
- `<OPENCODE_CONFIG>` — 真实 OpenCode 配置文件绝对路径
- `<HOME>/micromamba/...` — 真实 home 绝对前缀（Python 解释器路径）
- `<SERVER_USER_TYPO>` — 历史文档中记录的旧用户名拼写错误（同为身份近值）

deploy 模板 `{{RUN_USER}}` 示例值由真实账号改为通用示例 `appuser`。

## 3. Files Updated

以下文件在新历史的全部涉及 commit 中同步脱敏（仅机器身份信息，
不改变技术内容、结论与命令结构）：

- `docs/deployment/EasyModelGate-v0.1-Deployment.md`
- `docs/specifications/EasyModelGate-v0.1-Final-Specification.md`
- `docs/development/Phase-14-Deployment-Report.md`
- `docs/development/EasyModelGate-v0.1-Release-Closeout-Stage1.md`
- `docs/development/EasyModelGate-v0.1-Release-Closeout-Stage2.md`
- `docs/development/EasyModelGate-v0.1-Release-Pre-Audit.md`
- `docs/development/EasyModelGate-v0.1-Final-Release-Audit.md`
- `docs/development/EasyModelGate-v0.1-Release-Stage4A-First-Commit.md`
- `docs/development/EasyModelGate-v0.1-Release-Stage4B-GitHub-Publication.md`
- `docs/development/EasyModelGate-v0.1-Pre-Publication-Hygiene-Report.md`
- `deploy/README.md`

Pre-Publication Hygiene Report 予以保留，第一次 hygiene 的事实完整留存
（其中真实路径/用户名已按本节约定脱敏）。

核心运行代码 `easymodelgate/`、测试、实验脚本、fake upstream：
本轮 **零改动**（重扫确认原本即无机器身份硬编码）。

## 4. Technical History Preservation

以下技术历史记录按要求全部保留，不属于脱敏范围：

Qwen3.8-27B、GGUF / Q6_K、GPU 4–7、llama.cpp、CUDA / NVIDIA 实验记录、
Python 3.12.13 / micromamba、ctx=32768、Phase 0–14 全部过程记录、
OpenCode direct-vs-gateway A/B、protocol samples、fake upstream、
benchmark / timing、systemd 设计与 hardening 记录。

原则：清身份信息，不清技术证据。

## 5. Git Author Rewrite

新历史 4 个既有 commit 的 author 与 committer 全部统一为：

```
WingMoval <114322740+WingMoval@users.noreply.github.com>
```

原占位身份（服务器用户名 + 占位邮箱）不进入新历史。
原 commit message 与原始 author/committer 日期时间保持不变。

```
AUTHOR_REWRITE = PASS
```

## 6. Secret Scan

新 main 全 tracked 内容扫描（upstream / emg key 精确比对 +
github_pat_ / ghp_ / PRIVATE KEY / BEGIN RSA / BEGIN OPENSSH /
长 Bearer / password= 泛化，fake/test/example 语境判定）：

```
POST_SANITIZATION_SECRET_SCAN = PASS
```

生产 config.toml、upstream_key、data/、logs/、*.db*、.env、*.gguf
均不在 Git 跟踪范围（RELEASE_BOUNDARY_RECHECK = PASS）。

## 7. Privacy Scan

对当前 main 可达全部历史（4 commit + 本报告 commit）执行身份扫描：
真实服务器用户名 / 主机名 / 项目用户名 / 挂载 UUID（含前缀）/
真实绝对路径 / OpenCode 配置路径 → **0 命中**。

```
PUBLIC_IDENTITY_SCAN = PASS
FINAL_REPORT_SANITIZATION_CHECK = PASS   （本报告自身经独立扫描无隐私回流）
```

## 8. Portability

正式运行范围（`easymodelgate/`、`scripts/`、`configs/config.example.toml`、
`deploy/`、`.github/`、README×2、CHANGELOG、docs/releases/）扫描
真实用户名 / 主机名 / UUID / 绝对路径：0 命中。

```
POST_SANITIZATION_PORTABILITY = PASS
```

## 9. Fixed Model Dependency

核心源码 `easymodelgate/` 扫描 Qwen / Qwen3 / qwen3.8-local / 27B /
GGUF / *.gguf / CUDA_VISIBLE_DEVICES：**0 命中，行为依赖 0**。
tests / fake_upstream / perf 脚本环境变量默认值 / 历史 docs 命中按语境豁免。

```
FIXED_MODEL_DEPENDENCY_RECHECK = PASS
```

## 10. Test

重建后 HEAD（含本文件脱敏同步）全量回归：

```
环境：Python 3.12.13（easymodelgate-release-test）+ fake upstream（无 GPU 依赖）
结果：118 passed，0 failed（1 项已知第三方 warning）

POST_SANITIZATION_TEST = PASS
```

## 11. Git History

旧历史已整体重建废弃。最终 main 为 5 个 commit：

```
<commit5> docs: record final privacy sanitization     ← 本报告（SHA 见 R3 审计记录）
56abb6abddda049594d04c73e3bb1239ebf9fe45 docs: record pre-publication hygiene audit
8970f6a5bb0551683fab8c8aba873d5fd2e85748 docs: add v0.1.0 release publication records
87c09858b11b73ee8751a4180e13d17dac362b6b docs: add bilingual README for v0.1.0
ea605d254238d7ef0b0ffb8eb0bb018329f1185f feat: EasyModelGate v0.1.0 — lightweight local model API gateway
```

R2 重建前的 4 个 SHA 为 **obsolete pre-publication SHA（never released）**，
完整值已标注记录于 Pre-Publication Hygiene Report 第 8 节，此处不重复。

- 项目 refs 仅 `main`，无 tag、无 backup branch、无 refs/original、
  无 stale remote-tracking ref：`OLD_HISTORY_REACHABLE = NO`
- 旧历史仅存项目外保险（均 chmod 600，不入库、不上传）：
  `/tmp/easymodelgate-pre-rewrite-backup/EasyModelGate-before-hygiene.bundle`、
  `/tmp/easymodelgate-stage4b-r2-backup/EasyModelGate-before-final-sanitization.bundle`
- tracked log 文件数：0

## 12. Final Decision

```
FINAL_PRIVACY_SANITIZATION = PASS
```

冻结前置条件全部满足。进入 Stage 4B-R3
（Clean Remote Republish + Windows Final Audit + GitHub Actions
+ v0.1.0 annotated tag + GitHub Release）前，禁止任何 push，
等待人工审核。
