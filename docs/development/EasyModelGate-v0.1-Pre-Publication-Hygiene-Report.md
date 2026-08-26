# EasyModelGate v0.1.0 Pre-Publication Hygiene Report

- 日期：2026-08-26
- 前置：Remote Windows Release Audit = PASS（无 Release Blocker，
  两个 non-blocking hygiene items）

## 1. Background

Remote Windows 独立审计 PASS，但发现两个希望在正式公开 GitHub Release
前清理的非阻塞项：

1. experiments/phase-0.5/exp01~03 可执行脚本中固定路径
   `<OPENCODE_CONFIG>`；
2. exp04 下两个被跟踪的 `server.log`（内容仅为历史 NameError traceback
   与机器路径，信息价值低）。

由于 GitHub 远端将由人工删除并重建为空仓库、v0.1.0 尚未正式 Release，
本阶段对**本地未发布历史**执行了改写。

## 2. Changes

### exp01~03 OpenCode config path

三个脚本统一改为：

```python
OPENCODE_CONFIG = Path(
    os.environ.get(
        "EMG_OPENCODE_CONFIG",
        str(Path.home() / ".config" / "opencode" / "opencode.jsonc"),
    )
)
```

- 环境变量可完全覆盖；
- `Path.home()` 保证 Windows/Linux 用户目录均可解析；
- 不写死任何用户名；不打印 apiKey；
- 实验业务逻辑、JSON 解析逻辑、输入输出格式不变。

修改文件：
exp01_streaming_usage.py · exp02_sse_iterator.py · exp03_tool_calling.py

### 删除文件

- experiments/phase-0.5/exp04-client-disconnect/fake_upstream/server.log
- experiments/phase-0.5/exp04-client-disconnect/test_gateway/server.log

### .gitignore

新增全局 `*.log`（原仅覆盖 `logs/` 目录）；
临时 test.log 经 `git check-ignore -v` 验证生效。

### 文档数字同步

root commit 内的 Release Manifest 与 Final Release Audit 按删减后实测重算：
TOTAL 122 → **120**；EXPERIMENT 33 → **31**；
并在 Final Audit §2 增加 hygiene 说明句。
（后续 metadata/hygiene 提交新增的文档使树继续增长，属正常演进。）

## 3. Core Logic Impact

CORE_LOGIC_CHANGE = NO
（仅实验脚本路径获取方式与运行残留清理；Proxy/SSE/Auth/Quota/Analytics/
schema v1 零改动。）

## 4. Test

easymodelgate-release-test 环境：

```
118 passed / 0 failed（~21.6s）
POST_REWRITE_TEST = PASS
```

删除两个 server.log 不影响测试数量。

## 5. Secret Scan

对当前 tracked 全量候选扫描（upstream/emg 精确比对 + PRIVATE KEY/
BEGIN RSA/OPENSSH/github_pat_/ghp_/password= 泛化）：

```
POST_REWRITE_SECRET_SCAN = PASS
```

## 6. Portability

```
EXPERIMENT_EXECUTABLE_PATH_CHECK = PASS
（exp01~03 可执行脚本中固定 OpenCode 配置路径 0 命中；
 历史可达提交 pickaxe 扫描同样 0 命中）
```

## 7. Fixed Model Recheck

easymodelgate/ 核心源码 grep Qwen/Qwen3/GGUF/qwen3.8-local：**0 命中**
（tests fake upstream 常量、perf 脚本默认值、历史 docs 允许）。

```
FIXED_MODEL_DEPENDENCY_RECHECK = PASS
```

## 8. Git History Rewrite

| | old SHA（obsolete / never released） | 当轮 new SHA（后又被 R2 重建取代） | 最终 SHA（R2 重建后） |
|---|---|---|---|
| Commit 1 feat | ae8ba053dd81…28ca3ff | 7d34988ce788…a25f0 | **ea605d254238d7ef0b0ffb8eb0bb018329f1185f** |
| Commit 2 bilingual | c8c2b84…（bilingual README for v0.1.0） | 01b8b2259307…31b65 | **87c09858b11b73ee8751a4180e13d17dac362b6b** |
| Commit 3 publication records | d390e93…（release publication records） | bf2cc24c9367…43651 | **8970f6a5bb0551683fab8c8aba873d5fd2e85748** |
| Commit 4 hygiene（本报告） | —（本报告即当轮新增） | 4f5d4d4913c3…ade6c | **56abb6abddda049594d04c73e3bb1239ebf9fe45** |

完整旧 SHA（R1 改写前）：
ae8ba053dd8109e56b23112046104d25328ca3ff ·
c8c2b84（bilingual，全值见 bundle）·
d390e9326f6a53cce42726e12016f0a869ef4f77

完整旧 SHA（Stage 4B-R2 重建前，obsolete pre-publication / never released）：
7d34988ce788bcc092eb4d715ce8e40ae3ba25f0 ·
01b8b225930797733b16963c38e3497267431b65 ·
bf2cc24c936716a09f195c50dd3957e91e243651 ·
4f5d4d4913c30967904c52f25d5aac0c048ade6c

以上旧 SHA 一律视为 **obsolete pre-publication**：从未 push、从未打 tag、
从未创建 Release。改写前完整备份：
`/tmp/easymodelgate-pre-rewrite-backup/EasyModelGate-before-hygiene.bundle`（600）；
R2 重建前备份：
`/tmp/easymodelgate-stage4b-r2-backup/EasyModelGate-before-final-sanitization.bundle`（600）。

Stage4A / Stage4B 报告中用于"当前发布状态"的 SHA 已同步为 R2 重建后的最终值，
旧值保留并明确标注 obsolete pre-publication。
详见 `EasyModelGate-v0.1-Final-Privacy-Sanitization-Report.md`。

## 9. Final State

```
OLD_HISTORY_REACHABLE   = NO   （show-ref 无任何 ref 指向旧三 SHA）
TRACKED_LOG_COUNT       = 0
WORKTREE_CLEAN          = YES
refs/remotes/origin/main 已删除（配合远端仓库重建）
```

最终 main 历史（R2 重建后的最终 SHA；本报告终版随 R2 报告 commit 同步入库）：

```
56abb6a docs: record pre-publication hygiene audit      ← 本报告
8970f6a docs: add v0.1.0 release publication records
87c0985 docs: add bilingual README for v0.1.0
ea605d2 feat: EasyModelGate v0.1.0 — lightweight local model API gateway
```

## 10. Decision

```
PRE_PUBLICATION_HYGIENE = PASS
```
