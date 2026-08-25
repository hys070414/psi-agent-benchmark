#!/usr/bin/env python3
"""拉取服务器上最新生成的 benchmark 报告到本地。"""

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
KEY_FILE = os.getenv("TB_BENCH_KEY", "")
WORKDIR = os.getenv("TB_BENCH_WORKDIR", f"{os.getenv('HOME', '/root')}/psi-agent-benchmark")
LATEST_FILE = f"{WORKDIR}/pilot_results/LATEST_REPORT.txt"


def main():
    if not PASSWORD and not KEY_FILE:
        print("[fetch_report] error: TB_BENCH_KEY or TB_BENCH_PASSWORD not set in .env")
        sys.exit(1)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {"username": USER, "timeout": 20}
    if KEY_FILE:
        kwargs["key_filename"] = KEY_FILE
    elif PASSWORD:
        kwargs["password"] = PASSWORD
    client.connect(HOST, **kwargs)

    stdin, stdout, stderr = client.exec_command(f"cat {LATEST_FILE}", timeout=30)
    report_path = stdout.read().decode("utf-8", "ignore").strip().splitlines()[-1]
    err = stderr.read().decode("utf-8", "ignore")
    if err.strip():
        print("[fetch_report] error reading LATEST_REPORT.txt:", err)
        client.close()
        sys.exit(1)

    if not report_path or not report_path.endswith(".md"):
        print("[fetch_report] no report found on server yet")
        client.close()
        sys.exit(1)

    local_name = Path(report_path).name
    local_path = REPO_ROOT / "reports" / local_name
    local_path.parent.mkdir(parents=True, exist_ok=True)

    sftp = client.open_sftp()
    sftp.get(report_path, str(local_path))
    sftp.close()
    client.close()

    print(f"[fetch_report] downloaded {report_path}")
    print(f"[fetch_report] local copy: {local_path}")


if __name__ == "__main__":
    main()
