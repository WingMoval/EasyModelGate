# deploy/ — systemd 部署模板说明

本目录提供 EasyModelGate 的 systemd 服务**通用模板**。
模板中的 `{{...}}` 占位符需要你按自己的机器填写；
**示例里的占位符不是任何作者服务器的真实路径。**

> ⚠️ 安全提醒：不要把真实 API Key 写进 unit 文件或本目录。

## 两种部署方式

| 方式 | unit 位置 | 特点 |
|---|---|---|
| **用户级（推荐起步）** | `~/.config/systemd/user/` | 无需 root；日志走用户 journal；配合 linger 可开机自启 |
| **系统级** | `/etc/systemd/system/` | 需要 sudo；可声明对上游服务的 systemd 依赖；随 multi-user.target 启动 |

区别要点：系统级可以写 `Requires=llama-server.service` 这类跨服务依赖与
`User=` 指定运行账户；用户级则通过启动前健康检查脚本来等待上游就绪。

## 第一步：找到你的 Python 绝对路径

```bash
# micromamba / conda 环境
micromamba run -n <环境名> which python
# 或激活后
which python
```

得到形如 `/home/<你>/micromamba/envs/easymodelgate/bin/python` 的路径，
填入模板的 `{{PYTHON_BIN}}`。

## 第二步：找到项目绝对路径

```bash
cd /path/to/EasyModelGate && pwd
```

填入 `{{PROJECT_ROOT}}`；系统级模板同时填 `{{PROJECT_MOUNT_PATH}}`
（即 `pwd` 所在的挂载点根，例如某独立磁盘的挂载目录）。

## 第三步：复制并替换模板

```bash
mkdir -p ~/.config/systemd/user
sed -e "s|{{PROJECT_ROOT}}|$(pwd)|" \
    -e "s|{{PYTHON_BIN}}|$HOME/micromamba/envs/easymodelgate/bin/python|" \
    -e "s|{{UPSTREAM_HEALTH_URL}}|http://127.0.0.1:8080/health|" \
    deploy/easymodelgate-user.service.example \
    > ~/.config/systemd/user/easymodelgate.service
```

系统级同理，替换全部占位符后复制到 `/etc/systemd/system/`。

## 第四步：加载并启动

```bash
systemctl --user daemon-reload        # 系统级为：sudo systemctl daemon-reload
systemctl --user enable --now easymodelgate
systemctl --user status easymodelgate
```

## 第五步：健康检查

```bash
curl http://127.0.0.1:3000/health
# {"status":"ok","version":"0.1.0"}
```

## 系统级模板占位符清单

`easymodelgate-system.service.example` 额外包含以下占位符（用户级没有）：

| 占位符 | 含义 | 示例 |
|---|---|---|
| `{{RUN_USER}}` | 运行服务的普通用户名 | `appuser`、`www-data` 等 |
| `{{UPSTREAM_SYSTEMD_SERVICE}}` | 上游模型服务的 systemd 单元名；若上游不是 systemd 服务，删除 `Requires=` 行并保留健康门控脚本 | `llama-server.service` |
| `{{PROJECT_MOUNT_PATH}}` | 项目所在独立挂载盘的挂载点；项目不在独立盘上时删除 `RequiresMountsFor=` 行 | `/media/xxx/<uuid>` |

其余占位符与用户级一致。

## 常见问题

- **启动失败提示 upstream not ready**：上游模型服务未运行或 URL 不对。
- **重启服务器后服务没起来（用户级）**：需要开启 linger——
  `sudo loginctl enable-linger <你的用户名>`。
- **数据库/配置读不到**：确认 WorkingDirectory 正确，且该磁盘已挂载。
