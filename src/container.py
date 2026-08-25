"""Docker 容器管理 — 启动/停止/操作 Terminal-Bench 任务容器。"""

import json
import os
import subprocess
import time
import tomllib
from pathlib import Path


def run_cmd(cmd, *, cwd=None, timeout=None, capture=True, log_fn=None):
    """执行 shell 命令，可选捕获输出或直接透传。

    Args:
        cmd: 命令列表，如 ["docker", "ps"]。
        cwd: 工作目录。
        timeout: 超时秒数。
        capture: True 时捕获 stdout/stderr；False 时透传到终端。
        log_fn: 日志回调函数，接收字符串。

    Returns:
        subprocess.CompletedProcess 实例。
    """
    if log_fn:
        log_fn(f"CMD: {' '.join(cmd)} (cwd={cwd})")
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=capture, text=True, timeout=timeout
    )
    if log_fn:
        if result.returncode != 0:
            tail = ((result.stdout or "") + "\n" + (result.stderr or "")).strip().splitlines()[-50:]
            for line in tail:
                log_fn(f"  {line}")
        else:
            log_fn("  RC=0 OK")
    return result


def image_exists(tag):
    """检查 Docker 镜像是否存在。"""
    result = subprocess.run(
        ["docker", "images", "-q", tag], capture_output=True, text=True
    )
    return bool(result.stdout.strip())


def ensure_task_downloaded(name, tasks_dir, harbor_bin, log_fn=None):
    """下载 Terminal-Bench 任务定义（如未下载）。

    Returns:
        task_dir Path，失败返回 None。
    """
    task_dir = tasks_dir / name
    if task_dir.exists() and (task_dir / "task.toml").exists():
        return task_dir

    if log_fn:
        log_fn(f"Downloading task {name}...")
    result = run_cmd(
        [
            harbor_bin, "task", "download",
            f"terminal-bench/{name}",
            "--export", "--output-dir", str(tasks_dir), "--overwrite",
        ],
        timeout=300, capture=True, log_fn=log_fn,
    )
    return task_dir if result.returncode == 0 else None


def parse_task_toml(task_dir):
    """解析 task.toml 返回 dict。"""
    with open(task_dir / "task.toml", "rb") as f:
        return tomllib.load(f)


def start_env_container(container_name, image_tag, log_fn=None):
    """启动任务环境容器（后台 sleep infinity）。

    Returns:
        True 成功，False 失败。
    """
    run_cmd(["docker", "rm", "-f", container_name], capture=False, log_fn=log_fn)
    result = run_cmd(
        [
            "docker", "run", "-d", "--name", container_name,
            "-v", "/logs/verifier",
            image_tag, "sleep", "infinity",
        ],
        timeout=120, capture=True, log_fn=log_fn,
    )
    if result.returncode != 0:
        return False
    subprocess.run(
        ["docker", "exec", container_name, "mkdir", "-p", "/logs/verifier", "/app"],
        capture_output=True,
    )
    return True


def build_verifier_image(task_dir, tag, log_fn=None):
    """构建 verifier 镜像（如需要）。

    Returns:
        True 成功或已存在，False 构建失败。
    """
    dockerfile = task_dir / "tests" / "Dockerfile"
    if not dockerfile.exists():
        return False
    if image_exists(tag):
        if log_fn:
            log_fn(f"Verifier image {tag} exists, skip build")
        return True
    result = run_cmd(
        [
            "docker", "build", "-t", tag,
            "-f", str(dockerfile), str(task_dir / "tests"),
        ],
        timeout=3600, capture=True, log_fn=log_fn,
    )
    return result.returncode == 0


def run_agent(container_name, task_dir, result_dir, psi_dir, uv_bin, workspace, agent_timeout, log_fn=None):
    """在容器中运行 psi-agent。

    Returns:
        (returncode, status) — status 为 "finished" 或 "timeout"。
    """
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
        uv_bin, "run", "psi-agent", "ai",
        "--session-socket", ai_sock,
        "--provider", env.get("PSI_AI_PROVIDER", ""),
        "--model", env.get("PSI_AI_MODEL", ""),
        "--api-key", env.get("PSI_AI_API_KEY", ""),
        "--base-url", env.get("PSI_AI_BASE_URL", ""),
    ]
    sess_cmd = [
        uv_bin, "run", "psi-agent", "session",
        "--workspace", workspace,
        "--ai-socket", ai_sock,
        "--channel-socket", ch_sock,
    ]
    cli_cmd = [
        uv_bin, "run", "psi-agent", "channel", "cli",
        "--session-socket", ch_sock,
        "--message", (task_dir / "instruction.md").read_text(encoding="utf-8"),
    ]

    ai_proc = None
    sess_proc = None
    try:
        with open(ai_log_path, "w", encoding="utf-8") as ai_log:
            ai_proc = subprocess.Popen(ai_cmd, cwd=psi_dir, env=env, stdout=ai_log, stderr=subprocess.STDOUT)
        with open(sess_log_path, "w", encoding="utf-8") as sess_log:
            sess_proc = subprocess.Popen(sess_cmd, cwd=psi_dir, env=env, stdout=sess_log, stderr=subprocess.STDOUT)
        time.sleep(8)

        with open(agent_out_path, "w", encoding="utf-8") as agent_out:
            if log_fn:
                log_fn(f"Running agent with timeout {agent_timeout}s")
            try:
                cli_res = subprocess.run(
                    cli_cmd, cwd=psi_dir, env=env,
                    stdout=agent_out, stderr=subprocess.STDOUT,
                    timeout=agent_timeout,
                )
                return cli_res.returncode, "finished"
            except subprocess.TimeoutExpired:
                return -1, "timeout"
    finally:
        if log_fn:
            log_fn("Stopping agent processes")
        for proc in (sess_proc, ai_proc):
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                    proc.wait()


def run_verifier(container_name, task_dir, task_toml, verifier_tag, result_dir, log_fn=None):
    """运行 verifier 并提取 reward。

    Returns:
        reward 字符串（"1.0", "0.0", "unknown" 等）。
    """
    verifier = task_toml.get("verifier", {})
    mode = verifier.get("environment_mode", "same")
    if log_fn:
        log_fn(f"Verifier mode: {mode}")

    if mode == "separate":
        verifier_container = f"{container_name}-verifier"
        run_cmd(["docker", "rm", "-f", verifier_container], capture=False, log_fn=log_fn)
        run_cmd(
            [
                "docker", "run", "--rm", "--name", verifier_container,
                "--volumes-from", container_name,
                verifier_tag, "bash", "/tests/test.sh",
            ],
            timeout=600, capture=False, log_fn=log_fn,
        )
    else:
        subprocess.run(
            ["docker", "cp", str(task_dir / "tests"), f"{container_name}:/tests"],
            capture_output=True,
        )
        run_cmd(
            ["docker", "exec", container_name, "bash", "/tests/test.sh"],
            timeout=600, capture=False, log_fn=log_fn,
        )

    # 提取 reward
    reward = "unknown"
    reward_result = subprocess.run(
        ["docker", "exec", container_name, "cat", "/logs/verifier/reward.txt"],
        capture_output=True, text=True,
    )
    if reward_result.returncode == 0 and reward_result.stdout.strip():
        reward = reward_result.stdout.strip()

    # fallback: reward.json（某些 3.0 任务使用）
    if not reward or reward == "unknown":
        json_result = subprocess.run(
            ["docker", "exec", container_name, "cat", "/logs/verifier/reward.json"],
            capture_output=True, text=True,
        )
        if json_result.returncode == 0:
            try:
                reward_data = json.loads(json_result.stdout.strip())
                if isinstance(reward_data, dict) and "reward" in reward_data:
                    reward = str(reward_data["reward"])
            except Exception:
                pass

    verifier_log = result_dir / "verifier.log"
    verifier_log.write_text(f"verifier RC: {reward_result.returncode}\nreward: {reward}\n", encoding="utf-8")
    return reward


def cleanup_container(container_name, log_fn=None):
    """强制删除容器。"""
    run_cmd(["docker", "rm", "-f", container_name], capture=False, log_fn=log_fn)