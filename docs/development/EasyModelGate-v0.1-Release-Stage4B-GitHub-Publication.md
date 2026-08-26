# EasyModelGate v0.1.0 Stage 4B GitHub Publication Report

- 日期：2026-08-26
- 状态：**草稿** —— Tag / Release / 远端验证字段为 PENDING，待 push 后更新

## 1. Executive Summary

```
GITHUB_PUBLICATION = PENDING
```

本地发布前工作已全部完成（双语 README 提交 + 本报告所在元数据提交），
等待人工执行首次 push。

## 2. Bilingual README

| 文件 | 角色 | commit |
|---|---|---|
| README.md | English default page | BILINGUAL_README_COMMIT_SHA（见 §7） |
| README.zh-CN.md | 简体中文 | 同上 |

一致性检查：

```
BILINGUAL_README_CHECK = PASS
README_SECRET_CHECK    = PASS
README_PORTABILITY_CHECK = PASS
```

覆盖项核对：版本 v0.1.0、功能集 15+ 项、118 tests、
Linux + Python 3.12 + llama.cpp 兼容范围、Known Limitations 十条、
Apache-2.0、语言互链——两侧完全一致。

## 3. Local Pre-Push Validation

```
LOCAL_PRE_PUSH_TEST = PASS
pytest: 118 passed, 0 failed, 1 warning(第三方), duration≈21.8s
环境：easymodelgate-release-test（Python 3.12.13）
```

## 4. Repository / Remote

```
Repository URL : https://github.com/WingMoval/EasyModelGate
origin (fetch) = https://github.com/WingMoval/EasyModelGate.git
origin (push)  = https://github.com/WingMoval/EasyModelGate.git
REMOTE_CHECK   = PASS（fetch/push 双行一致）
```

远端仓库状态确认：空仓库（`git ls-remote` 无 ref），未做 pull/merge/force。

## 5. First Push

```
FIRST_PUSH = PENDING
命令：git push -u origin main
远端 main SHA 校验：待人工执行后回填
```

## 6. GitHub Actions

```
GITHUB_CI        = PENDING
workflow         = .github/workflows/tests.yml
期望             = 118 passed（fake upstream，无 GPU/真实上游依赖）
run URL          = PENDING
conclusion       = PENDING
```

CI_STATIC_CHECK = PASS（PyYAML 解析通过；无 Secret/机器路径/GPU 要求）。

## 7. Release Metadata Commit

```
RELEASE_METADATA_COMMIT_SHA = PENDING
message = docs: add v0.1.0 release publication records
包含   = Stage4A 报告 + 本 Stage4B 报告（恰两文件，index Secret 扫描见下）
METADATA_SECRET_SCAN = PENDING（提交动作随本文件一并完成后回填 PASS）
```

## 8. v0.1.0 Tag

```
TAG_PUSH          = PENDING
tag 类型          = annotated
指向              = RELEASE_METADATA_COMMIT_SHA（禁止移动）
```

## 9. GitHub Release

```
Release 创建      = PENDING
Title             = EasyModelGate v0.1.0
Notes 来源        = docs/releases/EasyModelGate-v0.1.0-Release-Notes.md
                  （顶部含英文 Summary，主体为中文正式说明）
附件              = 仅 GitHub 自动生成 Source code (zip/tar.gz)
```

## 10. Remote Clone Validation

```
REMOTE_CLONE_VALIDATION = PENDING
检查项：双语 README / CHANGELOG / tests / experiments / docs / deploy /
        LICENSE 在位；configs/config.toml / upstream_key / data / logs 缺席；
        git log 含三个预期 commit；tag v0.1.0 存在
```

## 11. Remote Secret Scan

```
REMOTE_SECRET_CHECK = PENDING
方法：clone 全量精确比对 upstream key 与 emg 测试 key
```

## 12. Final Git History

预期四 commit 形态：

```
7d34988 feat: EasyModelGate v0.1.0 — lightweight local model API gateway
         （注：ae8ba05 / c8c2b84 / d390e93 为 obsolete pre-publication SHA，
           pre-publication hygiene 历史改写前旧值，从未 push / Release）
<SHA2>  docs: add bilingual README for v0.1.0
<SHA3>  docs: add v0.1.0 release publication records   ← v0.1.0 tag 指向此处
<SHA4>  docs: finalize v0.1.0 publication report       （tag 之后追加）
```

当前实际进度：commit1 ✅ · commit2 ✅ · commit3 ✅（本文件与 Stage4A 报告）·
commit4 待发布结果回填。

## 13. Final Main CI

```
LATEST_MAIN_CI = PENDING
FINAL_MAIN_CI  = PENDING
```

## 14. Repository URLs

```
Repository : https://github.com/WingMoval/EasyModelGate
Actions    : https://github.com/WingMoval/EasyModelGate/actions
Releases   : https://github.com/WingMoval/EasyModelGate/releases
Release    : PENDING（创建后回填 …/releases/tag/v0.1.0）
```

## 15. Remaining Server Operations

以下属服务器运维收尾，非软件发布范畴：

- upstream key rotation（RECOMMEND_ROTATE_BEFORE_PUBLIC_RELEASE = YES）
- `sudo loginctl enable-linger <SERVER_USER>`
- 挂载盘写入 fstab
- scratch 测试 Key 与 /tmp 残留 housekeeping

## 16. Final Decision

等待 push 与 CI 结果后更新本节。
