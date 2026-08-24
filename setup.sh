#!/usr/bin/env bash
set -euo pipefail

# 部署脚本：在服务器上初始化 psi-agent + Terminal-Bench 环境

WORKDIR=${TB_BENCH_WORKDIR:-/root/haitun-tb}
PSI_DIR=$WORKDIR/psi-agent

echo "[setup] workdir: $WORKDIR"
mkdir -p $WORKDIR

# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 拉取 psi-agent（如尚未拉取）
if [ ! -d "$PSI_DIR/.git" ]; then
    echo "[setup] cloning psi-agent..."
    git clone https://github.com/hys070414/psi-agent.git $PSI_DIR
else
    echo "[setup] psi-agent already exists, pulling latest..."
    cd $PSI_DIR && git pull
fi

# 3. 将本仓库脚本复制/链接到 psi-agent 目录
cp run_all_cases.py $PSI_DIR/run_all_cases.py
cp generate_report.py $PSI_DIR/generate_report.py
cp case_metadata.json $WORKDIR/manifests/case_metadata.json
cp bin/run_benchmark.sh $PSI_DIR/run_benchmark.sh
chmod +x $PSI_DIR/run_benchmark.sh

# 4. 提示用户配置环境变量
if [ ! -f "$WORKDIR/.env" ]; then
    cp .env.example $WORKDIR/.env
    echo "[setup] created $WORKDIR/.env, please edit it with real credentials"
fi

echo "[setup] done. Next steps:"
echo "  1. edit $WORKDIR/.env"
echo "  2. build case images (see README)"
echo "  3. run: bash $PSI_DIR/run_benchmark.sh"
