# EasyModelGate v0.1.0 — Stage 4A：首次提交报告

- 日期：2026-08-26
- 前置：Final-Release-Audit = PASS · READY_FOR_FIRST_COMMIT = YES
- 结论：**FIRST_COMMIT = PASS**

## 1. Staged Manifest Match

```
STAGED_MANIFEST_MATCH = PASS
```

- staged 列表与 Manifest 严格集合比较完全一致（122 = 122）。
- 过程说明：初次比较出现假差异——git 2.7.4 对非 ASCII 路径默认八进制转义显示，
  且文件全部 staged 后 `add --dry-run` 不再输出。已改用
  `core.quotepath=false diff --cached --name-only`（index 权威列表）重建 Manifest
  （UTF-8 原文），并增加 WORKTREE_CROSS_CHECK 双重验证，均 PASS。
- 附带发现：Phase13 RC 快照曾以转义名复制过两份中文 ADR 副本（/tmp 临时目录内，
  非仓库），不影响仓库与历史。

## 2. Staged Secret Scan

对 **git index 中真实 staged 内容**（`git show :path`，非工作树文件）逐一扫描：

| 检查 | 结果 |
|---|---|
| upstream key 精确值 | 0 命中 |
| emg 测试 key 精确值 | 0 命中 |
| PRIVATE KEY / password= / 长 Bearer 泛化（tests 豁免假值） | 0 命中 |
| 中文 ADR 两文件补扫（转义路径导致的漏扫补充） | 0 命中 |

```
STAGED_SECRET_SCAN = PASS
```

## 3. Staged Privacy Scan

staged 清单 grep 校验：无 configs/config.toml、upstream_key、*.db(-wal/-shm)、
logs/、.env、OpenCode 配置类路径 → **PASS**。

## 4. Staged File Count

**122** —— 与 Manifest TOTAL_FILES 完全一致。

## 5. First Commit

```
SHA（current）                    = 7d34988ce788bcc092eb4d715ce8e40ae3ba25f0
                                     （pre-publication hygiene 历史改写后的当前 FIRST_COMMIT_SHA）
SHA（obsolete pre-publication）   = ae8ba053dd8109e56b23112046104d25328ca3ff
                                     （改写前旧值；从未 push / 打 tag / Release）
message  = feat: EasyModelGate v0.1.0 — lightweight local model API gateway
统计（current） = 120 files changed, 11295 insertions(+)
                   （移除两个无价值实验日志后的 root 提交规模；
                    obsolete：122 files / 11305 insertions）
类型     = 根提交（root commit）
分支     = main
```

## 6. Commit Secret Scan

对 `HEAD` 全部 tree 对象内容重扫（122 对象）：upstream/emg 精确比对 **0 命中**。

```
COMMIT_SECRET_SCAN = PASS
```

## 7. Git Status

```
working tree clean ✅
untracked: 无（Stage4A 报告在本检查之后创建）
ignored  : data/ logs/ configs/config.toml configs/upstream_key 等（预期）
```

## 8. Remote / Tag 状态

remote=0 · tag=0 · 未 push —— 符合停止点要求。

## 9. 下一阶段建议

人工审核本报告后：

1. 创建 GitHub Repository（建议名 `EasyModelGate`，私有→公开均可）；
2. `git remote add origin <url>` → `git push -u origin main`；
3. 打附注 tag 并发布：
   `git tag -a v0.1.0 -m "EasyModelGate v0.1.0" && git push origin v0.1.0`，
   Release 页面正文使用 `docs/releases/EasyModelGate-v0.1.0-Release-Notes.md`；
4. Release 后跟进运维事项：upstream key 轮换、enable-linger、fstab、
   scratch Key housekeeping；
5. 将本 Stage 4A 报告与后续 Phase 报告以独立 metadata commit 追加入库
   （例如 `docs: add stage 4A first-commit report`）。
