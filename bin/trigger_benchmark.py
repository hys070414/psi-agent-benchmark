#!/usr/bin/env python3
"""发布前测试：一键对指定分支的 Haitun 跑 Terminal-Bench 评测。

用法：
  python trigger_benchmark.py --branch feature-xxx
  python trigger_benchmark.py --branch feature-xxx --wait   # 等待跑完并自动下载报告
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

HOST = os.getenv("TB_BENCH_HOST", "152.42.223.183")
USER = os.getenv("TB_BENCH_USER", "root")
PASSWORD = os.getenv("TB_BENCH_PASSWORD", "")
KEY_FILE = os.getenv("TB_BENCH_KEY", "")
WORKDIR = os.getenv("TB_BENCH_WORKDIR", "/root/haitun-tb")
PSI_DIR = f"{WORKDIR}/psi-agent"
SETUP_SCRIPT = f"{WORKDIR}/setup.sh"
BENCH_SCRIPT = f"{PSI_DIR}/run_benchmark.sh"
RESULTS_DIR = f"{WORKDIR}/pilot_results"
LATEST_REPORT = f"{RESULTS_DIR}/LATEST_REPORT.txt"
MANIFEST_JSON = f"{WORKDIR}/manifests/benchmark_manifest.json"
POLL_INTERVAL = 60  # seconds


def ssh_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {"username": USER, "timeout": 30}
    if KEY_FILE:
        kwargs["key_filename"] = KEY_FILE
    elif PASSWORD:
        kwargs["password"] = PASSWORD
    else:
        print("[trigger] error: TB_BENCH_KEY or TB_BENCH_PASSWORD must be set in .env")
        sys.exit(1)
    c.connect(HOST, **kwargs)
    return c


def run_remote(cmd, timeout=60):
    c = ssh_client()
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    c.close()
    return out, err


def checkin():
    """确保服务器上已部署仓库和 psi-agent。"""
    print("[trigger] checking server environment ...")
    out, err = run_remote(f"test -f {SETUP_SCRIPT} && echo 'repo_ok' || echo 'no_repo'")
    if "no_repo" in out:
        print("[trigger] error: tb-bench-psi-agent repo not found on server at", WORKDIR)
        print("[trigger] please clone the repo to the server first:")
        print(f"  git clone <repo-url> {WORKDIR}")
        sys.exit(1)
    print("[trigger] repo found on server")


def deploy_branch(branch):
    """Checkout the target branch on server."""
    print(f"[trigger] deploying branch: {branch}")
    deploy_cmd = f"export PSI_AGENT_REF={branch}; bash {SETUP_SCRIPT}"
    out, err = run_remote(deploy_cmd, timeout=120)
    print(out)
    if err.strip():
        print("[trigger] setup stderr:", err[:500])


def launch_benchmark(branch):
    """Start benchmark in tmux on server."""
    session = f"tb-bench-{branch.replace('/', '-')}-{int(time.time())}"
    tmux_cmd = (
        f"tmux new-session -d -s {session} "
        f"\"cd {PSI_DIR} && python3 run_all_cases.py; "
        f"REPORT=\\$(python3 generate_report.py); "
        f"echo \\\"\\$REPORT\\\" > {LATEST_REPORT}; "
        f"echo '=== DONE ===' >> {RESULTS_DIR}/benchmark.log\""
    )
    print(f"[trigger] launching benchmark on server ...")
    out, err = run_remote(tmux_cmd, timeout=30)
    if err.strip():
        print("[trigger] launch error:", err)
    return session


def poll_completion(timeout_hours=12):
    """Poll until all 30 cases are done or timeout."""
    print("[trigger] waiting for benchmark to complete ...")
    deadline = time.time() + timeout_hours * 3600
    while time.time() < deadline:
        out, _ = run_remote(
            f"python3 -c \"import json; m=json.load(open('{MANIFEST_JSON}')); "
            f"done=sum(1 for v in m.values() if isinstance(v,dict) and v.get('reward') not in ('','unknown')); "
            f"print(f'{done}/{len([k for k in m if k!=\\\"_meta\\\"])}') if len(m)>1 else print('not_started')\"",
            timeout=30,
        )
        print(f"  [{time.strftime('%H:%M:%S')}] progress: {out.strip()}")
        if "/" in out and out.strip().split("/")[0] == out.strip().split("/")[1]:
            print("[trigger] all cases completed!")
            return True
        time.sleep(POLL_INTERVAL)
    print("[trigger] timeout waiting for benchmark")
    return False


def fetch_report():
    """Download the latest report from server."""
    print("[trigger] fetching report ...")
    out, _ = run_remote(f"cat {LATEST_REPORT}", timeout=30)
    if not out.strip() or not out.strip().endswith(".md"):
        print("[trigger] no report found on server yet")
        return None

    report_path = out.strip().splitlines()[-1].strip()
    local_dir = REPO_ROOT / "reports"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_name = Path(report_path).name
    local_path = local_dir / local_name

    c = ssh_client()
    sftp = c.open_sftp()
    sftp.get(report_path, str(local_path))
    sftp.close()
    c.close()

    print(f"[trigger] report saved: {local_path}")
    return local_path


def main():
    parser = argparse.ArgumentParser(description="发布前测试：对指定分支跑 TB benchmark")
    parser.add_argument("--branch", "-b", default="main", help="Haitun 分支名（默认 main）")
    parser.add_argument("--wait", "-w", action="store_true", help="等待跑完并自动下载报告")
    args = parser.parse_args()

    if not PASSWORD and not KEY_FILE:
        print("[trigger] error: TB_BENCH_KEY or TB_BENCH_PASSWORD must be set in .env")
        sys.exit(1)

    branch = args.branch
    print(f"[trigger] === Haitun 发布前测试 ===")
    print(f"[trigger] 分支: {branch}")
    print(f"[trigger] 服务器: {USER}@{HOST}")
    print()

    checkin()
    deploy_branch(branch)
    session = launch_benchmark(branch)

    print(f"\n[trigger] benchmark 已启动！")
    print(f"[trigger] tmux 会话: {session}")
    print(f"[trigger] 查看进度: ssh -t {USER}@{HOST} \"tmux attach -t {session}\"")
    print(f"[trigger] 或: ssh {USER}@{HOST} \"cat {RESULTS_DIR}/benchmark_status.txt\"")

    if args.wait:
        if poll_completion():
            fetch_report()
        else:
            print("[trigger] benchmark 仍在运行，报告未生成")
            print(f"[trigger] 稍后手工拉取: python bin/fetch_report.py")


if __name__ == "__main__":
    main()