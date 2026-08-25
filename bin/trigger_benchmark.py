#!/usr/bin/env python3
"""触发远程 benchmark 并自动拉取报告。

用法:
    python bin/trigger_benchmark.py                    # 仅触发，不等待
    python bin/trigger_benchmark.py --branch feature-x # 指定 psi-agent 分支
    python bin/trigger_benchmark.py --wait             # 触发后等待跑完，自动下载报告
"""

import argparse
import os
import sys
import time
from pathlib import Path

import paramiko
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

HOST = os.getenv("TB_BENCH_HOST", "")
USER = os.getenv("TB_BENCH_USER", "root")
PASSWORD = os.getenv("TB_BENCH_PASSWORD", "")
KEY_FILE = os.getenv("TB_BENCH_KEY", "")
WORKDIR = os.getenv("TB_BENCH_WORKDIR",
                    f"{os.getenv('HOME', '/root')}/psi-agent-benchmark")
REMOTE_RUNNER = f"{WORKDIR}/psi-agent/run_benchmark.sh"
RESULTS_DIR = f"{WORKDIR}/pilot_results"
LATEST_FILE = f"{RESULTS_DIR}/LATEST_REPORT.txt"
POLL_INTERVAL = 120  # 每 2 分钟检查一次


def connect():
    """建立 SSH 连接。"""
    if not HOST:
        sys.exit("[trigger] error: TB_BENCH_HOST not set in .env")
    if not KEY_FILE and not PASSWORD:
        sys.exit("[trigger] error: TB_BENCH_KEY or TB_BENCH_PASSWORD not set in .env")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {"username": USER, "timeout": 30}
    if KEY_FILE:
        kwargs["key_filename"] = KEY_FILE
    elif PASSWORD:
        kwargs["password"] = PASSWORD
    client.connect(HOST, **kwargs)
    return client


def trigger(client, branch):
    """在服务器上触发 benchmark。"""
    prefix = ""
    if branch:
        prefix = f"PSI_AGENT_REF={branch} "

    cmd = f"{prefix}bash {REMOTE_RUNNER}"
    print(f"[trigger] running: {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=60)

    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    print(out)
    if err.strip():
        print(f"[trigger] stderr: {err}")

    session = None
    for line in out.splitlines():
        if "tmux session:" in line:
            session = line.split("tmux session:")[-1].strip()
    return session


def wait_and_fetch(client, session):
    """轮询等待 benchmark 完成，然后下载报告。"""
    print(f"\n[trigger] waiting for benchmark to finish (session: {session})...")
    print(f"[trigger] polling every {POLL_INTERVAL}s — press Ctrl+C to stop waiting")

    while True:
        try:
            stdin, stdout, stderr = client.exec_command(
                f"cat {LATEST_FILE} 2>/dev/null", timeout=15
            )
            report_path = stdout.read().decode("utf-8", "ignore").strip()
            # 取最后一行（可能是多行输出）
            report_path = report_path.splitlines()[-1] if report_path else ""

            if report_path and report_path.endswith(".md"):
                print(f"\n[trigger] benchmark finished! report: {report_path}")
                return download_report(client, report_path)
        except Exception:
            pass

        # 显示进度估算
        try:
            stdin, stdout, stderr = client.exec_command(
                f"grep -c '===' {RESULTS_DIR}/benchmark.log 2>/dev/null || echo 0",
                timeout=10
            )
            progress = stdout.read().decode("utf-8", "ignore").strip()
            print(f"[trigger] still running... (progress hint: {progress})")
        except Exception:
            print("[trigger] still running...")

        time.sleep(POLL_INTERVAL)


def download_report(client, remote_path):
    """从服务器下载报告到本地 reports/ 目录。"""
    local_dir = REPO_ROOT / "reports"
    local_dir.mkdir(parents=True, exist_ok=True)

    local_name = Path(remote_path).name
    local_path = local_dir / local_name

    sftp = client.open_sftp()
    sftp.get(remote_path, str(local_path))
    sftp.close()

    print(f"[trigger] report downloaded to: {local_path}")
    return str(local_path)


def main():
    parser = argparse.ArgumentParser(description="Trigger remote benchmark")
    parser.add_argument("--branch", default=None,
                        help="psi-agent Git branch/tag to test")
    parser.add_argument("--wait", action="store_true",
                        help="Wait for benchmark to finish and download report")
    args = parser.parse_args()

    client = connect()
    print(f"[trigger] connected to {HOST}")

    try:
        session = trigger(client, args.branch)
        if not session:
            print("[trigger] warning: could not detect tmux session")
        else:
            print(f"\n[trigger] tmux session: {session}")
            print(f"[trigger] remote monitor: tmux attach -t {session}")

        if args.wait and session:
            wait_and_fetch(client, session)
    finally:
        client.close()


if __name__ == "__main__":
    main()