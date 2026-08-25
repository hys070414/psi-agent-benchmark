#!/usr/bin/env python3
"""Terminal-Bench 评测主流程 — 遍历 30 个 case，运行 agent + verifier，收集结果。"""

import json
import os
import sys
import time
import traceback
from pathlib import Path

# 将 src/ 加入 Python 路径，以便在 psi-agent 目录中也能导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.container import (
    run_cmd, image_exists, ensure_task_downloaded, parse_task_toml,
    start_env_container, build_verifier_image, run_agent, run_verifier,
    cleanup_container,
)

# ── 全局路径 ───────────────────────────────────────────────────────────────
WORKDIR = Path(os.environ.get(
    "TB_BENCH_WORKDIR",
    f"{os.environ.get('HOME', '/root')}/psi-agent-benchmark",
))
TASKS_DIR = WORKDIR / "tasks"
RESULTS_DIR = WORKDIR / "pilot_results"
MANIFEST_DIR = WORKDIR / "manifests"
MANIFEST_JSON = MANIFEST_DIR / "benchmark_manifest.json"
MANIFEST_MD = MANIFEST_DIR / "benchmark_manifest.md"
PSI_DIR = WORKDIR / "psi-agent"
HARBOR_BIN = os.environ.get("TB_HARBOR_BIN", "harbor")
UV_BIN = os.environ.get("TB_UV_BIN", "uv")
WORKSPACE = "examples/tb-pilot-workspace"


# ── 日志 ───────────────────────────────────────────────────────────────────
def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "benchmark.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── 配置加载 ───────────────────────────────────────────────────────────────
def load_env():
    """从 .env 文件加载环境变量。"""
    for env_file in (WORKDIR / ".env", PSI_DIR / ".env"):
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    os.environ[key] = val
            return


def load_cases():
    """从 case_metadata.json 读取启用的 case 列表。"""
    meta_path = MANIFEST_DIR / "case_metadata.json"
    if not meta_path.exists():
        log(f"ERROR: case_metadata.json not found at {meta_path}")
        return []
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    return [
        {
            "version": info["version"],
            "name": info["name"],
            "difficulty": info.get("difficulty", ""),
            "domain": info.get("domain", ""),
        }
        for key, info in sorted(metadata.items())
        if info.get("enabled", True)
    ]


def load_manifest():
    if MANIFEST_JSON.exists():
        with open(MANIFEST_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(manifest):
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_JSON, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    _write_manifest_md(manifest)


def _write_manifest_md(manifest):
    rows = [(item.get("order", 0), item) for key, item in manifest.items() if key != "_meta"]
    rows.sort(key=lambda x: x[0])
    lines = ["# TB Benchmark 结果清单\n\n"]
    lines.append(f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    lines.append("| # | 版本 | 任务名 | 领域 | 难度 | 状态 | Reward | 耗时 | 备注 |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|\n")
    total_reward = 0
    completed = 0
    for _, item in rows:
        reward = item.get("reward", "")
        if reward not in ("", None, "unknown"):
            completed += 1
            try:
                total_reward += float(reward)
            except Exception:
                pass
        lines.append(
            f"| {item.get('order', '')} | {item['version']} | {item['name']} | "
            f"{item.get('domain', '')} | {item.get('difficulty', '')} | "
            f"{item.get('agent_status', '')} | {reward} | "
            f"{item.get('elapsed_sec', '')} | {item.get('note', '')} |\n"
        )
    lines.append(f"\n汇总：完成 {completed}/{len(rows)} 个 case，总 reward {total_reward:.2f}。\n")
    with open(MANIFEST_MD, "w", encoding="utf-8") as f:
        f.write("".join(lines))


def get_agent_version():
    ref = os.environ.get("PSI_AGENT_REF", "main")
    try:
        commit = __import__("subprocess").check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PSI_DIR, text=True
        ).strip()
        return f"{ref}@{commit}"
    except Exception:
        return ref


# ── 主流程 ─────────────────────────────────────────────────────────────────
def main():
    load_env()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest()
    model = os.environ.get("PSI_AI_MODEL", "unknown")
    agent_version = get_agent_version()
    start_epoch = time.time()
    start_ts = time.strftime("%Y-%m-%d %H:%M:%S")

    cases = load_cases()
    if not cases:
        log("ERROR: no cases loaded from case_metadata.json")
        sys.exit(1)

    manifest["_meta"] = {
        "model": model,
        "agent_version": agent_version,
        "start_time": start_ts,
        "start_epoch": start_epoch,
        "total_cases": len(cases),
    }
    save_manifest(manifest)
    log(f"Benchmark started: model={model}, agent={agent_version}, cases={len(cases)}")

    for idx, case in enumerate(cases, 1):
        version = case["version"]
        name = case["name"]
        key = f"{version}/{name}"
        image_tag = f"tb-{version}-{name}:latest"
        verifier_tag = f"tb-{version}-{name}-verifier:latest"
        container_name = f"tb-agent-{version}-{name}"
        result_dir = RESULTS_DIR / name
        result_dir.mkdir(parents=True, exist_ok=True)

        # 跳过已完成的 case
        if key in manifest and manifest[key].get("reward") not in ("", "unknown"):
            log(f"=== [{idx}/{len(cases)}] {key} already completed (reward={manifest[key].get('reward')}), skipping ===")
            continue

        log(f"=== [{idx}/{len(cases)}] {key} ===")
        start_time = time.time()
        item = {
            "order": idx,
            "version": version,
            "name": name,
            "domain": case.get("domain", ""),
            "difficulty": case.get("difficulty", ""),
            "image_tag": image_tag,
            "agent_status": "pending",
            "reward": "",
            "elapsed_sec": "",
            "note": "",
            "result_dir": str(result_dir),
        }

        try:
            # 1. 下载任务
            task_dir = ensure_task_downloaded(name, TASKS_DIR, HARBOR_BIN, log_fn=log)
            if task_dir is None:
                item["agent_status"] = "download_failed"
                item["note"] = "harbor download failed"
                manifest[key] = item
                save_manifest(manifest)
                continue

            task_toml = parse_task_toml(task_dir)
            agent_timeout = min(task_toml.get("agent", {}).get("timeout_sec", 1800), 3600)

            # 2. 检查镜像
            if not image_exists(image_tag):
                item["agent_status"] = "image_missing"
                item["note"] = f"image {image_tag} not found"
                manifest[key] = item
                save_manifest(manifest)
                continue

            # 3. 启动容器
            if not start_env_container(container_name, image_tag, log_fn=log):
                item["agent_status"] = "container_failed"
                item["note"] = "failed to start env container"
                manifest[key] = item
                save_manifest(manifest)
                continue

            # 4. 构建 verifier（如需要）
            verifier_mode = task_toml.get("verifier", {}).get("environment_mode", "same")
            if verifier_mode == "separate":
                if not build_verifier_image(task_dir, verifier_tag, log_fn=log):
                    item["agent_status"] = "verifier_build_failed"
                    item["note"] = "failed to build verifier image"
                    manifest[key] = item
                    save_manifest(manifest)
                    cleanup_container(container_name, log_fn=log)
                    continue

            # 5. 运行 agent
            rc, status = run_agent(
                container_name, task_dir, result_dir,
                PSI_DIR, UV_BIN, WORKSPACE, agent_timeout,
                log_fn=log,
            )
            item["agent_status"] = status if rc == 0 else f"agent_{status}_rc{rc}"

            # 6. 运行 verifier
            reward = run_verifier(container_name, task_dir, task_toml, verifier_tag, result_dir, log_fn=log)
            item["reward"] = reward

            # 7. 清理
            cleanup_container(container_name, log_fn=log)

            elapsed = int(time.time() - start_time)
            item["elapsed_sec"] = elapsed
            item["note"] = f"completed in {elapsed}s"
            manifest[key] = item
            save_manifest(manifest)

        except Exception as e:
            log(f"Exception for {key}: {e}\n{traceback.format_exc()}")
            item["agent_status"] = "error"
            item["note"] = str(e)[:200]
            cleanup_container(container_name, log_fn=log)
            manifest[key] = item
            save_manifest(manifest)

    # 汇总
    end_epoch = time.time()
    elapsed = int(end_epoch - start_epoch)
    meta = manifest.get("_meta", {})
    meta.update({
        "end_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "end_epoch": end_epoch,
        "elapsed_sec": elapsed,
    })
    manifest["_meta"] = meta
    log(f"=== Benchmark complete in {elapsed}s ===")
    save_manifest(manifest)


if __name__ == "__main__":
    main()