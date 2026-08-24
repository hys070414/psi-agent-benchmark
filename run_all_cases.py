#!/usr/bin/env python3
"""Run psi-agent on the full 30-case TB 2.1/3.0 subset and collect verify rewards."""

import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import traceback
from pathlib import Path

WORKDIR = Path(os.environ.get("TB_BENCH_WORKDIR", "/root/haitun-tb"))
TASKS_DIR = WORKDIR / "tasks"
RESULTS_DIR = WORKDIR / "pilot_results"
MANIFEST_DIR = WORKDIR / "manifests"
MANIFEST_JSON = MANIFEST_DIR / "benchmark_manifest.json"
MANIFEST_MD = MANIFEST_DIR / "benchmark_manifest.md"
PSI_DIR = WORKDIR / "psi-agent"
HARBOR_BIN = os.environ.get("TB_HARBOR_BIN", "/root/miniconda3/bin/harbor")
UV_BIN = os.environ.get("TB_UV_BIN", "/root/.local/bin/uv")
WORKSPACE = "examples/tb-pilot-workspace"

def load_cases():
    """Load case list from case_metadata.json. Only returns enabled cases."""
    meta_path = MANIFEST_DIR / "case_metadata.json"
    if not meta_path.exists():
        log(f"ERROR: case_metadata.json not found at {meta_path}")
        return []
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    cases = []
    for key, info in sorted(metadata.items()):
        if not info.get("enabled", True):
            continue
        cases.append({
            "version": info["version"],
            "name": info["name"],
            "difficulty": info.get("difficulty", ""),
            "domain": info.get("domain", ""),
        })
    return cases


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "benchmark.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_env():
    """Load psi-agent .env into os.environ — try WORKDIR first, then PSI_DIR."""
    env_file = WORKDIR / ".env"
    if not env_file.exists():
        env_file = PSI_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ[key] = val


def load_manifest():
    if MANIFEST_JSON.exists():
        with open(MANIFEST_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(manifest):
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_JSON, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    write_markdown(manifest)


def write_markdown(manifest):
    rows = [(item.get("order", 0), item) for key, item in manifest.items() if key != "_meta"]
    rows.sort(key=lambda x: x[0])
    lines = ["# TB 2.1/3.0 子集 psi-agent benchmark 结果清单\n\n"]
    lines.append(f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    lines.append("| 序号 | 版本 | 任务名 | 领域 | 难度 | Agent状态 | Reward | 耗时 | 备注 |\n")
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
            f"| {item.get('order', '')} | {item['version']} | {item['name']} | {item.get('domain', '')} | "
            f"{item.get('difficulty', '')} | {item.get('agent_status', '')} | {reward} | "
            f"{item.get('elapsed_sec', '')} | {item.get('note', '')} |\n"
        )
    lines.append(f"\n汇总：完成 {completed}/{len(rows)} 个 case，总 reward {total_reward:.2f}。\n")
    with open(MANIFEST_MD, "w", encoding="utf-8") as f:
        f.write("".join(lines))


def run_cmd(cmd, cwd=None, timeout=None, capture=True):
    log(f"COMMAND: {' '.join(cmd)} (cwd={cwd})")
    if capture:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    else:
        result = subprocess.run(cmd, cwd=cwd, text=True, timeout=timeout)
    if result.returncode != 0:
        log(f"  RC={result.returncode}")
        tail = ((result.stdout or "") + "\n" + (result.stderr or "")).strip().splitlines()[-50:]
        for line in tail:
            log(f"    {line}")
    else:
        log(f"  RC=0 OK")
    return result


def image_exists(tag):
    result = subprocess.run(["docker", "images", "-q", tag], capture_output=True, text=True)
    return bool(result.stdout.strip())


def ensure_task_downloaded(name):
    task_dir = TASKS_DIR / name
    if not task_dir.exists() or not (task_dir / "task.toml").exists():
        log(f"Downloading task {name}...")
        result = run_cmd([
            HARBOR_BIN, "task", "download",
            f"terminal-bench/{name}",
            "--export", "--output-dir", str(TASKS_DIR), "--overwrite",
        ], timeout=300)
        if result.returncode != 0:
            return None
    return task_dir


def parse_task_toml(task_dir):
    with open(task_dir / "task.toml", "rb") as f:
        return tomllib.load(f)


def start_env_container(container_name, image_tag):
    run_cmd(["docker", "rm", "-f", container_name], capture=False)
    result = run_cmd([
        "docker", "run", "-d", "--name", container_name,
        "-v", "/logs/verifier",
        image_tag, "sleep", "infinity",
    ], timeout=120)
    if result.returncode != 0:
        return False
    # ensure /logs/verifier and /app exist
    subprocess.run(["docker", "exec", container_name, "mkdir", "-p", "/logs/verifier", "/app"], capture_output=True)
    return True


def build_verifier_image(task_dir, tag):
    dockerfile = task_dir / "tests" / "Dockerfile"
    if not dockerfile.exists():
        return False
    if image_exists(tag):
        log(f"Verifier image {tag} exists, skip build")
        return True
    result = run_cmd([
        "docker", "build", "-t", tag,
        "-f", str(dockerfile), str(task_dir / "tests"),
    ], timeout=3600)
    return result.returncode == 0


def run_agent(container_name, task_dir, result_dir, agent_timeout):
    env = os.environ.copy()
    env["PSI_PILOT_CONTAINER"] = container_name

    ai_sock = f"/tmp/psi-ai-{container_name}.sock"
    ch_sock = f"/tmp/psi-ch-{container_name}.sock"
    for sock in (ai_sock, ch_sock):
        Path(sock).unlink(missing_ok=True)

    ai_log_path = result_dir / "ai.log"
    sess_log_path = result_dir / "session.log"
    agent_out_path = result_dir / "agent_output.log"

    ai_cmd = [
        UV_BIN, "run", "psi-agent", "ai",
        "--session-socket", ai_sock,
        "--provider", env.get("PSI_AI_PROVIDER", ""),
        "--model", env.get("PSI_AI_MODEL", ""),
        "--api-key", env.get("PSI_AI_API_KEY", ""),
        "--base-url", env.get("PSI_AI_BASE_URL", ""),
    ]
    sess_cmd = [
        UV_BIN, "run", "psi-agent", "session",
        "--workspace", WORKSPACE,
        "--ai-socket", ai_sock,
        "--channel-socket", ch_sock,
    ]
    cli_cmd = [
        UV_BIN, "run", "psi-agent", "channel", "cli",
        "--session-socket", ch_sock,
        "--message", (task_dir / "instruction.md").read_text(encoding="utf-8"),
    ]

    ai_proc = None
    sess_proc = None
    try:
        with open(ai_log_path, "w", encoding="utf-8") as ai_log:
            ai_proc = subprocess.Popen(ai_cmd, cwd=PSI_DIR, env=env, stdout=ai_log, stderr=subprocess.STDOUT)
        with open(sess_log_path, "w", encoding="utf-8") as sess_log:
            sess_proc = subprocess.Popen(sess_cmd, cwd=PSI_DIR, env=env, stdout=sess_log, stderr=subprocess.STDOUT)
        time.sleep(8)

        with open(agent_out_path, "w", encoding="utf-8") as agent_out:
            log(f"Running agent with timeout {agent_timeout}s")
            try:
                cli_res = subprocess.run(cli_cmd, cwd=PSI_DIR, env=env, stdout=agent_out, stderr=subprocess.STDOUT, timeout=agent_timeout)
                return cli_res.returncode, "finished"
            except subprocess.TimeoutExpired:
                return -1, "timeout"
    finally:
        log("Stopping agent processes")
        for proc in (sess_proc, ai_proc):
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                    proc.wait()


def run_verifier(container_name, task_dir, task_toml, verifier_tag, result_dir):
    verifier = task_toml.get("verifier", {})
    mode = verifier.get("environment_mode", "same")
    log(f"Verifier mode: {mode}")

    if mode == "separate":
        # run verifier container with volumes-from env
        verifier_container = f"{container_name}-verifier"
        run_cmd(["docker", "rm", "-f", verifier_container], capture=False)
        result = run_cmd([
            "docker", "run", "--rm", "--name", verifier_container,
            "--volumes-from", container_name,
            verifier_tag, "bash", "/tests/test.sh",
        ], timeout=600, capture=False)
    else:
        # copy tests into env container and run
        subprocess.run(["docker", "cp", str(task_dir / "tests"), f"{container_name}:/tests"], capture_output=True)
        result = run_cmd([
            "docker", "exec", container_name, "bash", "/tests/test.sh",
        ], timeout=600, capture=False)

    # save verifier output
    verifier_log = result_dir / "verifier.log"
    # since capture=False, no output captured; attempt to fetch reward from verifier artifacts
    reward = "unknown"
    reward_result = subprocess.run(
        ["docker", "exec", container_name, "cat", "/logs/verifier/reward.txt"],
        capture_output=True, text=True
    )
    if reward_result.returncode == 0:
        reward = reward_result.stdout.strip()
    # fallback to /logs/verifier/reward.json (JSON reward format used by some 3.0 tasks)
    if not reward or reward == "unknown":
        json_result = subprocess.run(
            ["docker", "exec", container_name, "cat", "/logs/verifier/reward.json"],
            capture_output=True, text=True
        )
        if json_result.returncode == 0:
            try:
                reward_data = json.loads(json_result.stdout.strip())
                if isinstance(reward_data, dict) and "reward" in reward_data:
                    reward = str(reward_data["reward"])
            except Exception:
                pass
    verifier_log.write_text(f"verifier RC: {result.returncode}\nreward: {reward}\n", encoding="utf-8")
    return reward


def cleanup_container(container_name):
    run_cmd(["docker", "rm", "-f", container_name], capture=False)


def rotate_benchmark_log():
    log_path = RESULTS_DIR / "benchmark.log"
    if log_path.exists():
        backup = RESULTS_DIR / f"benchmark.{time.strftime('%Y%m%d_%H%M%S')}.log"
        log_path.rename(backup)
        log(f"Rotated old benchmark.log to {backup}")


def get_model():
    return os.environ.get("PSI_AI_MODEL", "unknown")


def get_agent_version():
    ref = os.environ.get("PSI_AGENT_REF", "main")
    psi_dir = PSI_DIR
    try:
        import subprocess
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=psi_dir, text=True
        ).strip()
        return f"{ref}@{commit}"
    except Exception:
        return ref


def main():
    load_env()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rotate_benchmark_log()
    manifest = load_manifest()

    model = get_model()
    agent_version = get_agent_version()
    start_ts = time.strftime("%Y-%m-%d %H:%M:%S")
    start_epoch = time.time()
    cases = load_cases()
    if not cases:
        log("ERROR: no cases loaded from case_metadata.json")
        sys.exit(1)
    manifest["_meta"] = {
        "model": model,
        "agent_version": agent_version,
        "start_time": start_ts,
        "start_epoch": start_epoch,
        "timeout_cap_sec": 3600,
        "total_cases": len(cases),
    }
    save_manifest(manifest)
    log(f"Benchmark started: model={model}, agent_version={agent_version}, cases={len(cases)}")

    for idx, case in enumerate(cases, 1):
        version = case["version"]
        name = case["name"]
        key = f"{version}/{name}"
        image_tag = f"tb-{version}-{name}:latest"
        verifier_tag = f"tb-{version}-{name}-verifier:latest"
        container_name = f"tb-agent-{version}-{name}"
        result_dir = RESULTS_DIR / name
        result_dir.mkdir(parents=True, exist_ok=True)

        # skip if already completed in a previous run
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
            # 1. ensure task downloaded
            task_dir = ensure_task_downloaded(name)
            if task_dir is None:
                item["agent_status"] = "download_failed"
                item["note"] = "harbor download failed"
                manifest[key] = item
                save_manifest(manifest)
                continue

            task_toml = parse_task_toml(task_dir)
            agent_timeout = task_toml.get("agent", {}).get("timeout_sec", 1800)
            agent_timeout = min(agent_timeout, 3600)  # cap at 60 min per case

            # 2. start env container
            if not image_exists(image_tag):
                item["agent_status"] = "image_missing"
                item["note"] = f"image {image_tag} not found"
                manifest[key] = item
                save_manifest(manifest)
                continue

            if not start_env_container(container_name, image_tag):
                item["agent_status"] = "container_failed"
                item["note"] = "failed to start env container"
                manifest[key] = item
                save_manifest(manifest)
                continue

            # 3. build verifier image if separate
            verifier_mode = task_toml.get("verifier", {}).get("environment_mode", "same")
            if verifier_mode == "separate":
                if not build_verifier_image(task_dir, verifier_tag):
                    item["agent_status"] = "verifier_build_failed"
                    item["note"] = "failed to build verifier image"
                    manifest[key] = item
                    save_manifest(manifest)
                    cleanup_container(container_name)
                    continue

            # 4. run agent
            rc, status = run_agent(container_name, task_dir, result_dir, agent_timeout)
            item["agent_status"] = status if rc == 0 else f"agent_{status}_rc{rc}"

            # 5. run verifier
            reward = run_verifier(container_name, task_dir, task_toml, verifier_tag, result_dir)
            item["reward"] = reward

            # 6. cleanup
            cleanup_container(container_name)

            elapsed = int(time.time() - start_time)
            item["elapsed_sec"] = elapsed
            item["note"] = f"completed in {elapsed}s"
            manifest[key] = item
            save_manifest(manifest)

        except subprocess.TimeoutExpired:
            log(f"Timeout for {key}")
            item["agent_status"] = "timeout"
            item["note"] = "overall timeout"
            cleanup_container(container_name)
            manifest[key] = item
            save_manifest(manifest)
        except Exception as e:
            log(f"Exception for {key}: {e}\n{traceback.format_exc()}")
            item["agent_status"] = "error"
            item["note"] = str(e)
            cleanup_container(container_name)
            manifest[key] = item
            save_manifest(manifest)

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
