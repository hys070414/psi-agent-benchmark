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

# 从 case_metadata.json 读取启用的 case 列表
CASES_JSON="$MANIFEST_DIR/case_metadata.json"
if [ ! -f "$CASES_JSON" ]; then
    echo "[build] ERROR: $CASES_JSON not found" | tee -a "$BUILD_LOG"
    exit 1
fi

# 用 python3 解析 JSON，输出 "version/name" 格式的 case 列表
readarray -t CASES < <(python3 -c "
import json
with open('$CASES_JSON') as f:
    meta = json.load(f)
for key, info in sorted(meta.items()):
    if info.get('enabled', True):
        print(key)
")

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