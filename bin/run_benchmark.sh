#!/usr/bin/env bash
set -euo pipefail

WORKDIR=${TB_BENCH_WORKDIR:-/root/haitun-tb}
PSI_DIR=$WORKDIR/psi-agent
RESULTS_DIR=$WORKDIR/pilot_results
MANIFEST_DIR=$WORKDIR/manifests
PSI_AGENT_REF=${PSI_AGENT_REF:-main}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TMUX_SESSION="tb-bench-${TIMESTAMP}"
MANIFEST_JSON=$MANIFEST_DIR/benchmark_manifest.json

echo "[run_benchmark] workdir: $WORKDIR"
echo "[run_benchmark] psi-agent ref: $PSI_AGENT_REF"

cd "$WORKDIR"

# Optionally re-setup to ensure correct psi-agent version is checked out
	if [ -f "./setup.sh" ]; then
	    echo "[run_benchmark] running setup.sh to ensure psi-agent version $PSI_AGENT_REF"
	    bash ./setup.sh
	fi
	
	# Build Docker images if missing (skip if images already exist)
	if [ -f "./build_images.sh" ]; then
	    echo "[run_benchmark] building missing Docker images ..."
	    bash ./build_images.sh
	fi
	
	# Backup old manifest so previous runs are not lost
if [ -f "$MANIFEST_JSON" ]; then
    BACKUP="$MANIFEST_DIR/benchmark_manifest.${TIMESTAMP}.json"
    cp "$MANIFEST_JSON" "$BACKUP"
    echo "[run_benchmark] backed up old manifest to $BACKUP"
fi

# Clear manifest for a fresh run
rm -f "$MANIFEST_JSON"

# Optionally rotate the main benchmark.log
if [ -f "$RESULTS_DIR/benchmark.log" ]; then
    mv "$RESULTS_DIR/benchmark.log" "$RESULTS_DIR/benchmark.${TIMESTAMP}.log"
    echo "[run_benchmark] rotated old benchmark.log"
fi

# Build the tmux command:
# 1. run all cases
# 2. generate the data-only report
# 3. write the report path to a known marker file
# 4. keep the session alive so logs can be inspected
TMUX_CMD="
set -e
cd $PSI_DIR
echo '[run_benchmark] starting benchmark at \$(date)'
python3 run_all_cases.py
REPORT=\$(python3 generate_report.py)
echo \"\$REPORT\" > $RESULTS_DIR/LATEST_REPORT.txt
echo '[run_benchmark] benchmark finished at \$(date); report:'
echo \"\$REPORT\"
exec bash
"

tmux new-session -d -s "$TMUX_SESSION" "$TMUX_CMD"

echo "[run_benchmark] benchmark launched in tmux session: $TMUX_SESSION"
echo "[run_benchmark] monitor: tmux attach -t $TMUX_SESSION"
echo "[run_benchmark] when done, report path will be written to $RESULTS_DIR/LATEST_REPORT.txt"
