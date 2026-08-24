#!/usr/bin/env bash
# ============================================================
# 构建 Terminal-Bench 30 个 case 的 Docker 镜像
# 用法: bash build_images.sh [--force]
#   --force  强制重建所有镜像（忽略已有镜像）
# ============================================================
set -euo pipefail

WORKDIR=${TB_BENCH_WORKDIR:-/root/haitun-tb}
TASKS_DIR="$WORKDIR/tasks"
LOG_DIR="$WORKDIR/pilot_results"
MANIFEST_DIR="$WORKDIR/manifests"
HARBOR_BIN="${HARBOR_BIN:-harbor}"
FORCE=false

if [ "${1:-}" = "--force" ]; then
    FORCE=true
    echo "[build] --force: rebuilding all images"
fi

mkdir -p "$TASKS_DIR" "$LOG_DIR" "$MANIFEST_DIR"
BUILD_LOG="$LOG_DIR/build_images.log"
echo "[build] $(date) start" | tee "$BUILD_LOG"

# 30 cases
CASES=(
    "2.1/cobol-modernization"
    "2.1/fix-git"
    "2.1/overfull-hbox"
    "2.1/prove-plus-comm"
    "2.1/caffe-cifar-10"
    "2.1/chess-best-move"
    "2.1/largest-eigenval"
    "2.1/crack-7z-hash"
    "2.1/filter-js-from-html"
    "2.1/polyglot-c-py"
    "2.1/db-wal-recovery"
    "2.1/rstan-to-pystan"
    "2.1/configure-git-webserver"
    "2.1/install-windows-3.11"
    "2.1/llm-inference-batching-scheduler"
    "3.0/foodstuff-beta-activity"
    "3.0/photonic-waveguide-routing"
    "3.0/vllm-deepseek-streaming"
    "3.0/medical-claims-processing"
    "3.0/interleaved-vigenere"
    "3.0/freecad-platform-drawing"
    "3.0/music-harmony"
    "3.0/bun-sourcemap-leak"
    "3.0/atrx-vep-crispr"
    "3.0/live-database-cutover"
    "3.0/fin-saccr-rwa"
    "3.0/satb-audio-transcription"
    "3.0/takens-embedding-lean"
    "3.0/gpt2-codegolf"
    "3.0/retro-console-soc"
)

total=${#CASES[@]}
ok=0
fail=0

for i in "${!CASES[@]}"; do
    entry="${CASES[$i]}"
    version="${entry%%/*}"
    name="${entry#*/}"
    idx=$((i + 1))
    image_tag="tb-${version}-${name}:latest"
    verifier_tag="tb-${version}-${name}-verifier:latest"

    echo "" | tee -a "$BUILD_LOG"
    echo "=== [$idx/$total] $entry ===" | tee -a "$BUILD_LOG"

    # skip if image already exists
    if ! $FORCE && docker images -q "$image_tag" > /dev/null 2>&1; then
        echo "  [skip] image $image_tag already exists" | tee -a "$BUILD_LOG"
        ok=$((ok + 1))
        continue
    fi

    # download task
    echo "  [download] $name ..." | tee -a "$BUILD_LOG"
    if $HARBOR_BIN task download "terminal-bench/${name}" \
        --export --output-dir "$TASKS_DIR" --overwrite >> "$BUILD_LOG" 2>&1; then
        echo "  [download] OK" | tee -a "$BUILD_LOG"
    else
        echo "  [download] FAILED" | tee -a "$BUILD_LOG"
        fail=$((fail + 1))
        continue
    fi

    task_dir="$TASKS_DIR/$name"
    if [ ! -f "$task_dir/task.toml" ]; then
        echo "  [error] task.toml not found in $task_dir" | tee -a "$BUILD_LOG"
        fail=$((fail + 1))
        continue
    fi

    # build env image
    echo "  [build] $image_tag ..." | tee -a "$BUILD_LOG"
    if $HARBOR_BIN task build "terminal-bench/${name}" \
        --tag "$image_tag" >> "$BUILD_LOG" 2>&1; then
        echo "  [build] OK" | tee -a "$BUILD_LOG"
    else
        echo "  [build] FAILED, trying docker build from Dockerfile ..." | tee -a "$BUILD_LOG"
        # fallback: try direct docker build
        if [ -f "$task_dir/Dockerfile" ]; then
            if docker build -t "$image_tag" -f "$task_dir/Dockerfile" "$task_dir" >> "$BUILD_LOG" 2>&1; then
                echo "  [build] OK (docker)" | tee -a "$BUILD_LOG"
            else
                echo "  [build] FAILED" | tee -a "$BUILD_LOG"
                fail=$((fail + 1))
                continue
            fi
        else
            echo "  [build] FAILED (no Dockerfile fallback)" | tee -a "$BUILD_LOG"
            fail=$((fail + 1))
            continue
        fi
    fi

    # build verifier image if separate
    if [ -f "$task_dir/tests/Dockerfile" ]; then
        if ! $FORCE && docker images -q "$verifier_tag" > /dev/null 2>&1; then
            echo "  [verifier] $verifier_tag already exists, skip" | tee -a "$BUILD_LOG"
        else
            echo "  [verifier] building $verifier_tag ..." | tee -a "$BUILD_LOG"
            if docker build -t "$verifier_tag" \
                -f "$task_dir/tests/Dockerfile" "$task_dir/tests" >> "$BUILD_LOG" 2>&1; then
                echo "  [verifier] OK" | tee -a "$BUILD_LOG"
            else
                echo "  [verifier] FAILED" | tee -a "$BUILD_LOG"
            fi
        fi
    fi

    ok=$((ok + 1))
done

echo "" | tee -a "$BUILD_LOG"
echo "=== BUILD SUMMARY ===" | tee -a "$BUILD_LOG"
echo "  total: $total, ok: $ok, fail: $fail" | tee -a "$BUILD_LOG"
echo "  log: $BUILD_LOG" | tee -a "$BUILD_LOG"

# generate image manifest
MANIFEST_MD="$MANIFEST_DIR/image_manifest.md"
echo "# TB Docker 镜像清单" > "$MANIFEST_MD"
echo "" >> "$MANIFEST_MD"
echo "生成时间: $(date)" >> "$MANIFEST_MD"
echo "" >> "$MANIFEST_MD"
echo "| 序号 | 版本 | Case | 镜像 | 状态 |" >> "$MANIFEST_MD"
echo "|---|---|---|---|---|" >> "$MANIFEST_MD"
for i in "${!CASES[@]}"; do
    entry="${CASES[$i]}"
    version="${entry%%/*}"
    name="${entry#*/}"
    idx=$((i + 1))
    image_tag="tb-${version}-${name}:latest"
    if docker images -q "$image_tag" > /dev/null 2>&1; then
        status="✅"
    else
        status="❌"
    fi
    echo "| $idx | $version | $name | $image_tag | $status |" >> "$MANIFEST_MD"
done
echo "" >> "$MANIFEST_MD"
echo "镜像清单已保存到 $MANIFEST_MD" | tee -a "$BUILD_LOG"

exit $([ $fail -eq 0 ] && echo 0 || echo 1)