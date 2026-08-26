# EasyModelGate v0.1.0 Release Closeout — Stage 2（Release Candidate Validation）

- 日期：2026-08-26
- 前置：Stage 1 = PASS
- 结论：**RELEASE_CLOSEOUT_STAGE2 = PASS**

```
CLEAN_ENV_TEST        = PASS
README_STEP_TEST      = PASS
CI_READY              = YES
SECRET_SCAN_RC        = PASS
PORTABILITY_RC_CHECK  = PASS
```

## 1. 阶段目标

在全新隔离环境与干净快照中，以"陌生用户视角"完成安装→配置→启动→功能→
测试全链路；固化 GitHub Actions CI；二次 Secret/迁移性扫描。
零业务功能变更（唯一代码改动为一处测试自洽性修正，见 §8）。

## 2. 新环境创建

| 项 | 值 |
|---|---|
| 环境名 | `easymodelgate-release-test`（独立创建，未复用 dev/test/prod） |
| Python | 3.12.13 |
| pip | 26.1.2 |
| conda 阶段耗时 | 12s |
| pip 安装耗时 | 28s（`PIP_CONFIG_FILE=/dev/null` + 清华源，绕过失效 nvidia extra-index） |
| 解析结果 | fastapi 0.141.1 / starlette 1.6.0 / httpx 0.28.1 / uvicorn 0.52.4 / aiosqlite 0.22.1 / pydantic 2.13.4 / pytest 9.1.1 —— 与冻结版本逐一相等 |

严格依据仓库公开文件 `requirements.txt` 安装。

## 3. Release Candidate 快照

- 路径：`/tmp/easymodelgate-release-candidate/`
- 构建方式：按 `git add --dry-run .` 候选清单**逐文件复制**（等效陌生用户 clone）
- 总数：116 个文件（Stage1 报告 115 + Stage1 报告自身；本阶段再增 CI 与本报告，
  终态候选数见 §15）
- 必备资产 13 项全部在位（easymodelgate/tests/experiments/docs/deploy/scripts/
  README/LICENSE/requirements/environment.yml/pyproject/config.example/.gitignore）
- 生产排除项验证：config.toml / upstream_key / data / logs **均不存在** ✅
- 快照 Secret 精确比对 PASS

## 4. 从零配置

- `cp configs/config.example.toml configs/config.toml` 后仅改三处：
  port=13000、database.path=/tmp 下独立 RC SQLite、base_url=127.0.0.1:18080
- `configs/upstream_key` 写入 fake 值（chmod 600）
- 未触碰生产 config.toml / data/easymodelgate.db / :3000 / :8080 ✅

## 5. CLI 初始化验证（release-test 环境）

`python -m easymodelgate --help` 正常；随后：

- user create rc-user → key create（完整 Key 仅 stdout 一次）
- user list / key list 正常
- usage summary 空库输出 TOTAL 行不报错
- 新库自动创建：schema_version=1 ✓；backend seed=(local-llamacpp, llamacpp) ✓；
  key_hash 全为 64 位 hex、库中仅存 hash/prefix ✓

## 6. 服务独立启动

fake upstream（tests/fake_upstream/server.py，端口 18080）+ RC 网关（端口 13000）：

| 检查 | 结果 |
|---|---|
| GET /health | 200 {"status":"ok","version":"0.1.0"} |
| GET /v1/models | 200 |
| POST non-stream | "hello"，tokens=19 |
| POST stream | 200，[DONE] 收尾 |

完全独立于生产实例运行 ✅

## 7. 功能迁移验证（复用现有 tests）

直接在快照目录运行既有 pytest（未新写任何测试）——Auth/models/non-stream/
streaming/Tool Calling(fake)/usage/request logging/RPM/Soft quota/SQLite restart
persistence 全部包含其中并通过。

## 8. 全量 118 项自动测试（release-test 环境 × 干净快照）

```
collected = 118
passed    = 118
failed    = 0
warnings  = 1（starlette 第三方弃用提示，Phase 12 已审计记录）
duration  ≈ 21.8s
```

**证明 118 项测试不依赖 easymodelgate-dev 的任何隐藏依赖。**

### 测试自洽性修正（非业务 Bug）

`test_config_env_override` 原隐式依赖"cwd 存在 configs/config.toml"，
在干净 clone 中会触发 fail-fast。已改为用例内自备配置文件 + EMG_CONFIG 定向，
使该用例在任何 cwd/CI 成立。修改文件：
`tests/integration/test_cli.py`（仅该用例）。修正后全量仍 118 passed。

## 9. package / import 验证

- `pip install -e .`（pyproject setuptools 构建）：成功
- 项目外目录（cwd=/tmp）`import easymodelgate` → `__version__ == "0.1.0"` ✅
- console script `easymodelgate --help` 可用（安装于环境 bin/，激活后进 PATH）
- 验证后已卸载 editable 安装，恢复源码直跑形态

结论：当前 pyproject 已支持正式安装方式；无需 packaging 改造。

## 10. README 步骤实测

按「快速开始」逐条以陌生用户身份执行（env 名替换为 release-test 即可，
其余零改动）：clone(等价快照) → pip install → cp example 配置 → 配置 upstream
key 文件 → serve → user/key create → curl health/models/chat —— 全部成立。

```
README_STEP_TEST = PASS
```

无需修正 README 步骤本身。

## 11. systemd 模板验证（静态）

- 两模板 grep `/home/<SERVER_USER>|/media/<SERVER_USER>|<MOUNT_UUID>|<SERVER_HOSTNAME>`：**0 命中**
- 占位符清单 vs deploy/README.md 说明：PROJECT_ROOT/PYTHON_BIN/
  UPSTREAM_HEALTH_URL/PROJECT_MOUNT_PATH 均有说明；
  本次补齐系统级专属三项说明：RUN_USER / UPSTREAM_SYSTEMD_SERVICE /
  PROJECT_MOUNT_PATH 表格化说明
- 未安装到生产 systemd；生产 unit 未修改

## 12. GitHub Actions

新增 `.github/workflows/tests.yml`：ubuntu-latest + Python 3.12 +
`pip install -r requirements.txt` + `pytest -q`。
无 GPU / 无真实 llama.cpp / 无真实 upstream Key / 不读生产配置
（conftest 全部走 fake upstream + tmp_path 数据库）。

```
CI_EXPECTED_TEST_COUNT = 118   # 快照实测全部可在 CI 条件下通过
```

Badge：remote 未定，暂不加（避免写死不存在 URL）。

## 13. Secret Scan（终态候选）

对含 .github/workflows 与本报告在内的最终候选集重新执行
精确比对 + 泛化模式扫描：**0 命中**。

```
SECRET_SCAN_RC = PASS
```

## 14. Portability Check（终态候选）

扫描范围：easymodelgate/ scripts/ configs/config.example.toml deploy/
.github/ README.md —— `/home/<SERVER_USER>`、`/media/<SERVER_USER>`、`<MOUNT_UUID>`、
`<SERVER_HOSTNAME>` 均 **0 命中**（历史 docs/experiments 中的实例记录按要求豁免）。

```
PORTABILITY_RC_CHECK = PASS
```

## 15. Git candidate 状态

- 分支 main、HEAD 无 commit、无 remote、无 tag（保持 Stage 1 状态）
- 最终候选数：**117 个文件**
  （115 → +Stage1 报告 →116 → +tests 自洽修正属改非增 → +CI workflow →117
   → +本报告 →117+1=118？以最终 `git add --dry-run | wc -l` 实测值为准，
   见下方"终态实测"补记）
- MUST_NOT_COMMIT 进入候选数：**0**（check-ignore 复核）

> 终态实测补记：报告落盘后实测候选 118 个文件（新增本报告与 workflow 后），
> 敏感项仍全部 ignored。

## 16. 本阶段临时资源清理

已停止并删除：RC fake upstream 进程、RC 网关进程、
`/tmp/easymodelgate-release-candidate/` 目录、rc.db/rc 日志/临时 runner。
保留：`easymodelgate-release-test` 环境（待人工审核后再决定去留）、
生产 systemd/数据库/Key 全部原状。

## 17. Release 风险

1. CI 首跑需 GitHub Actions 配额/网络可达 PyPI；工作流未做缓存优化（P2）。
2. starlette testclient 弃用警告延续存在（第三方，Phase 12 已记录）。
3. 用户级部署的开机自启仍依赖运维 enable-linger（Phase 14 已交接）。

## 18. 下一步建议

人工审核后依次执行：首次 commit（建议 message：
`feat: EasyModelGate v0.1.0 — lightweight local model API gateway`）→
添加远端 → push → 打 tag v0.1.0 并发 Release（附 Phase 12/13 报告摘要）；
发布后在服务器执行 upstream key 轮换与 enable-linger 两项运维交接。
