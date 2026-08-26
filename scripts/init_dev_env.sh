#!/usr/bin/env bash
# EasyModelGate 开发环境初始化（幂等）
set -euo pipefail

ENV_NAME="${ENV_NAME:-easymodelgate-dev}"
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
PY="$MAMBA_ROOT_PREFIX/envs/$ENV_NAME/bin/python"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$PY" ]; then
    echo "[init] 创建 micromamba 环境 $ENV_NAME (python=3.12.13)"
    micromamba create -y -n "$ENV_NAME" python=3.12.13
fi

echo "[init] 安装冻结依赖"
"$PY" -m pip install --quiet -r "$ROOT/requirements.txt"

echo "[init] 完成：$PY"
echo "[init] 运行测试：cd $ROOT && $PY -m pytest -q"
echo "[init] 启动服务：$PY -m easymodelgate --config configs/config.toml serve"
