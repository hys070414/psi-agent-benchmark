#!/usr/bin/env bash
# ============================================================================
# auto_bench.sh — 全无人值守评测 + 自动交付报告
#
# 用法:
#   bash bin/auto_bench.sh                                  # 本地生成报告并写出 LATEST_REPORT.txt
#   GITHUB_TOKEN=ghp_xxx bash bin/auto_bench.sh             # 额外把报告推送到仓库 reports 分支
#
# 说明:
#   - 先调用 run_benchmark.sh（在服务器 tmux 中跑 eval + generate_report）
#   - 轮询 pilot_results/LATEST_REPORT.txt，直到出现以 .md 结尾的报告路径
#   - 把最新报告复制进 reports/latest_report.md
#   - 若设置了 GITHUB_TOKEN，则提交并推送到仓库的 reports 分支（不动 main）
# ============================================================================
set -uo pipefail

WORKDIR="${TB_BENCH_WORKDIR:-$HOME/psi-agent-benchmark}"
RESULTS_DIR="$WORKDIR/pilot_results"
REPO="https://github.com/hys070414/psi-agent-benchmark.git"

cd "$WORKDIR"

echo "[auto_bench] launching benchmark..."
bash bin/run_benchmark.sh

echo "[auto_bench] waiting for report marker (LATEST_REPORT.txt)..."
REPORT_PATH=""
for i in $(seq 1 720); do  # 最多等 2 小时
    if [ -f "$RESULTS_DIR/LATEST_REPORT.txt" ]; then
        CANDIDATE=$(tail -n1 "$RESULTS_DIR/LATEST_REPORT.txt" | tr -d '\r')
        # 兼容可能的 "Report written to <path>" 前缀
        case "$CANDIDATE" in
            *"Report written to "*) CANDIDATE="${CANDIDATE#*Report written to }" ;;
        esac
        CANDIDATE="$(echo "$CANDIDATE" | xargs)"
        case "$CANDIDATE" in
            *.md)
                REPORT_PATH="$CANDIDATE"
                echo "[auto_bench] report ready: $REPORT_PATH"
                break
                ;;
        esac
    fi
    sleep 10
done

if [ -z "$REPORT_PATH" ] || [ ! -f "$REPORT_PATH" ]; then
    echo "[auto_bench] ERROR: report not found. Check $RESULTS_DIR/benchmark.log"
    exit 1
fi

mkdir -p "$WORKDIR/reports"
cp "$REPORT_PATH" "$WORKDIR/reports/latest_report.md"
echo "[auto_bench] copied to $WORKDIR/reports/latest_report.md"

if [ -n "${GITHUB_TOKEN:-}" ]; then
    echo "[auto_bench] pushing report to 'reports' branch..."
    TS=$(date +%Y%m%d_%H%M%S)
    git add reports/latest_report.md
    git -c "user.name=psi-bench-bot" -c "user.email=bot@psi.local" \
        commit -m "auto: benchmark report $TS" || echo "[auto_bench] nothing to commit"
    git push "https://${GITHUB_TOKEN}@github.com/hys070414/psi-agent-benchmark.git" \
        HEAD:refs/heads/reports || echo "[auto_bench] push skipped/failed"
else
    echo "[auto_bench] GITHUB_TOKEN not set — skipping push. Others can retrieve via:"
    echo "             python bin/fetch_report.py"
fi

echo "[auto_bench] done."
