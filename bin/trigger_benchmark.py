#!/usr/bin/env python3
"""本地一键触发远程 TB benchmark。"""

import os
import sys
from pathlib import Path

import paramiko
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

HOST = os.getenv("TB_BENCH_HOST", "152.42.223.183")
USER = os.getenv("TB_BENCH_USER", "root")
PASSWORD = os.getenv("TB_BENCH_PASSWORD", "")
WORKDIR = os.getenv("TB_BENCH_WORKDIR", "/root/haitun-tb")
REMOTE_SCRIPT = f"{WORKDIR}/psi-agent/run_benchmark.sh"


def main():
    if not PASSWORD:
        print("[trigger_benchmark] error: TB_BENCH_PASSWORD not set in .env")
        sys.exit(1)

    print(f"[trigger_benchmark] connecting to {USER}@{HOST} ...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=20)

    stdin, stdout, stderr = client.exec_command(f"bash {REMOTE_SCRIPT}", timeout=60)
    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    print(out)
    if err.strip():
        print("--- STDERR ---")
        print(err)

    session = None
    for line in out.splitlines():
        if "tmux session:" in line:
            session = line.split("tmux session:")[-1].strip()

    client.close()

    if session:
        print(f"\n[trigger_benchmark] session: {session}")
        print(f"[trigger_benchmark] monitor: tmux attach -t {session}")
        print(f"[trigger_benchmark] from local: ssh -t {USER}@{HOST} \"tmux attach -t {session}\"")
    else:
        print("[trigger_benchmark] could not detect tmux session")


if __name__ == "__main__":
    main()
