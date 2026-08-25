#!/usr/bin/env python3
"""触发远程 benchmark 并自动拉取报告。

用法:
    python bin/trigger_benchmark.py                    # 仅触发，不等待
    python bin/trigger_benchmark.py --branch feature-x # 指定 psi-agent 分支
    python bin/trigger_benchmark.py --wait             # 触发后等待跑完，自动下载报告
    python bin/trigger_benchmark.py --cases fix-git,caffe-cifar-10 --wait
    python bin/trigger_benchmark.py --versions 2.1 --difficulties 易 --wait
    python bin/trigger_benchmark.py --pick --wait      # 交互式选择 case 后触发
"""

import argparse
import json
import os
import shlex
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
LOCAL_CASE_METADATA = REPO_ROOT / "config" / "case_metadata.json"


def pick_cases_locally():
    """在本地交互式选择 case（按 TB 2.1 / 3.0 分组），返回选中的名称列表。

    选择结果会作为 --cases 参数传给远程，远程按名称精确匹配。

    Returns:
        选中的 case 名称列表；放弃时返回 None。
    """
    if not LOCAL_CASE_METADATA.exists():
        sys.exit(f"[trigger] error: case metadata not found: {LOCAL_CASE_METADATA}")
    with open(LOCAL_CASE_METADATA, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # 按 version 分组，组内按名称排序
    by_version = {}
    for key, info in sorted(metadata.items()):
        by_version.setdefault(info["version"], []).append((key, info))

    numbered = []  # [(编号, key, info)]
    print()
    for version in sorted(by_version.keys()):
        cases = by_version[version]
        print(f"─── TB {version}（{len(cases)} 个）───")
        for key, info in cases:
            idx = len(numbered) + 1
            numbered.append((idx, key, info))
            flag = "" if info.get("enabled", True) else "  [已禁用]"
            print(f"  {idx:>2}. {info['name']:<40} {info.get('difficulty', ''):<4} {info.get('domain', '')}{flag}")
        print()

    print("输入编号选择（示例: 1,3-5,12  或  2.1  或  3.0  或  a 全选，q 放弃）:")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[pick] 已放弃选择")
            return None
        if not raw:
            continue
        if raw.lower() == "q":
            print("[pick] 已放弃选择")
            return None
        if raw.lower() == "a":
            selected_keys = {k for _, k, _ in numbered}
        elif raw in by_version:
            selected_keys = {k for k, _ in by_version[raw]}
        else:
            selected_keys = set()
            ok = True
            for part in raw.replace("，", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    lo, _, hi = part.partition("-")
                    try:
                        lo_i, hi_i = int(lo), int(hi)
                    except ValueError:
                        print(f"  无效范围: {part}")
                        ok = False
                        break
                    if lo_i < 1 or hi_i > len(numbered) or lo_i > hi_i:
                        print(f"  编号超出范围 1-{len(numbered)}: {part}")
                        ok = False
                        break
                    for n in range(lo_i, hi_i + 1):
                        selected_keys.add(numbered[n - 1][1])
                else:
                    try:
                        n = int(part)
                    except ValueError:
                        print(f"  无效编号: {part}")
                        ok = False
                        break
                    if n < 1 or n > len(numbered):
                        print(f"  编号超出范围 1-{len(numbered)}: {n}")
                        ok = False
                        break
                    selected_keys.add(numbered[n - 1][1])
            if not ok or not selected_keys:
                continue

        names = [info["name"] for _, key, info in numbered if key in selected_keys]
        print(f"\n[pick] 已选择 {len(names)} 个 case:")
        for _, key, info in numbered:
            if key in selected_keys:
                print(f"  {key}")
        try:
            confirm = input("确认执行远程评测? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n[pick] 已放弃选择")
            return None
        if confirm in ("", "y", "yes"):
            return names
        print()


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


def trigger(client, branch, case_args=None):
    """在服务器上触发 benchmark。

    Args:
        client: paramiko SSHClient
        branch: psi-agent Git 分支名，None 则用默认
        case_args: 额外的 case 选择参数列表，如 ["--versions", "2.1", "--limit", "5"]
    """
    prefix = ""
    if branch:
        prefix = f"PSI_AGENT_REF={branch} "

    # 将 case 选择参数注入到远程命令
    case_env = ""
    if case_args:
        case_env = f'TB_CASE_ARGS={shlex.quote(" ".join(case_args))} '

    cmd = f"{prefix}{case_env}bash {REMOTE_RUNNER}"
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
            # 兼容 generate_report.py 旧版可能输出 "Report written to <path>"
            if "Report written to" in report_path:
                report_path = report_path.split("Report written to")[-1].strip()

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
    parser = argparse.ArgumentParser(
        description="Trigger remote benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  # 跑所有 case
  python bin/trigger_benchmark.py --wait

  # 交互式选择：按 TB 2.1/3.0 分组列出，输入编号挑选
  python bin/trigger_benchmark.py --pick --wait

  # 只跑指定 case
  python bin/trigger_benchmark.py --cases fix-git,caffe-cifar-10 --wait

  # 只跑 2.1 版本
  python bin/trigger_benchmark.py --versions 2.1 --wait

  # 只跑容易的，最多 3 个
  python bin/trigger_benchmark.py --difficulties 易 --limit 3 --wait
""",
    )
    parser.add_argument("--branch", default=None,
                        help="psi-agent Git branch/tag to test")
    parser.add_argument("--wait", action="store_true",
                        help="Wait for benchmark to finish and download report")
    parser.add_argument("--cases", "-c", action="append", default=None, metavar="NAME[,NAME...]",
                        help="精确指定 case 名称（逗号分隔），可多次使用")
    parser.add_argument("--versions", "-v", default=None, metavar="V[,V...]",
                        help="版本筛选，逗号分隔（如 2.1 或 2.1,3.0）")
    parser.add_argument("--difficulties", "-d", default=None, metavar="D[,D...]",
                        help="难度筛选，逗号分隔（如 易 或 易,中,难）")
    parser.add_argument("--exclude", action="append", default=None, metavar="KEY",
                        help="排除的 case key（如 2.1/fix-git），可多次使用")
    parser.add_argument("--limit", "-n", type=int, default=None, metavar="N",
                        help="最多运行的 case 数量")
    parser.add_argument("--pick", "-p", action="store_true",
                        help="本地交互式选择 case（按 TB 2.1/3.0 分组），选中后触发远程评测")
    args = parser.parse_args()

    # 构建 case 选择参数，传递给远程 run_all_cases.py
    case_args = []
    if args.pick:
        picked = pick_cases_locally()
        if picked is None:
            print("[trigger] 未选择任何 case，退出")
            sys.exit(0)
        if not picked:
            print("[trigger] 选择的 case 为空，退出")
            sys.exit(1)
        case_args.extend(["--cases", ",".join(picked)])
    if args.cases:
        for chunk in args.cases:
            case_args.extend(["--cases", chunk])
    if args.versions:
        case_args.extend(["--versions", args.versions])
    if args.difficulties:
        case_args.extend(["--difficulties", args.difficulties])
    if args.exclude:
        for ex in args.exclude:
            case_args.extend(["--exclude", ex])
    if args.limit is not None:
        case_args.extend(["--limit", str(args.limit)])

    client = connect()
    print(f"[trigger] connected to {HOST}")

    try:
        session = trigger(client, args.branch, case_args=case_args)
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