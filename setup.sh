#!/usr/bin/env bash
set -euo pipefail

# 部署脚本：在服务器上初始化 psi-agent + Terminal-Bench 环境

WORKDIR=${TB_BENCH_WORKDIR:-/root/haitun-tb}
PSI_DIR=$WORKDIR/psi-agent
PSI_AGENT_REF=${PSI_AGENT_REF:-main}
PSI_AGENT_REPO=${PSI_AGENT_REPO:-https://github.com/genuineknowledge/psi-agent.git}

echo "[setup] workdir: $WORKDIR"
echo "[setup] psi-agent version/ref: $PSI_AGENT_REF"
mkdir -p $WORKDIR

# 1. 安装 Python 依赖（本地触发用，服务器上可能不需要）
pip install -r requirements.txt 2>/dev/null || pip3 install -r requirements.txt 2>/dev/null || echo "[setup] pip not available, skipping Python dependencies"

# 2. 拉取 psi-agent 并切换到指定版本
if [ ! -d "$PSI_DIR/.git" ]; then
    echo "[setup] cloning psi-agent..."
	    git clone $PSI_AGENT_REPO $PSI_DIR
fi

cd $PSI_DIR
	git fetch origin
	git checkout "$PSI_AGENT_REF"
	git pull origin "$PSI_AGENT_REF" || true
	cd $WORKDIR
	
	echo "[setup] current psi-agent commit: $(cd $PSI_DIR && git rev-parse --short HEAD)"
	
	# 3. 将本仓库脚本复制到工作目录
	cp $WORKDIR/run_all_cases.py $PSI_DIR/run_all_cases.py
	cp $WORKDIR/generate_report.py $PSI_DIR/generate_report.py
	cp $WORKDIR/build_images.sh $WORKDIR/build_images.sh
	chmod +x $WORKDIR/build_images.sh
	mkdir -p $WORKDIR/manifests
	cp $WORKDIR/case_metadata.json $WORKDIR/manifests/case_metadata.json
	cp $WORKDIR/bin/run_benchmark.sh $PSI_DIR/run_benchmark.sh
	chmod +x $PSI_DIR/run_benchmark.sh

# 4. 提示用户配置环境变量
if [ ! -f "$WORKDIR/.env" ]; then
    cp $WORKDIR/.env.example $WORKDIR/.env
    echo "[setup] created $WORKDIR/.env, please edit it with real credentials"
fi

echo "[setup] done. Next steps:"
echo "  1. edit $WORKDIR/.env"
echo "  2. build case images (see README)"
echo "  3. run: bash $PSI_DIR/run_benchmark.sh"
