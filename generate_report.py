#!/usr/bin/env python3
"""Generate a data-only benchmark report from manifest + logs."""

import json
import os
import sys
import time
from pathlib import Path

WORKDIR = Path(os.environ.get("TB_BENCH_WORKDIR", "/root/haitun-tb"))
MANIFEST_JSON = WORKDIR / "manifests" / "benchmark_manifest.json"
METADATA_JSON = WORKDIR / "manifests" / "case_metadata.json"
RESULTS_DIR = WORKDIR / "pilot_results"
CHARS_PER_TOKEN = 4.0
LOG_TAIL_LINES = 30


def read_text(path, default=""):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return default


def count_chars(path):
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def tail_lines(text, n):
    lines = text.splitlines()
    return "\n".join(lines[-n:]) if lines else ""


def estimate_tokens(case_name):
    result_dir = RESULTS_DIR / case_name
    ai_log = result_dir / "ai.log"
    session_log = result_dir / "session.log"
    agent_out = result_dir / "agent_output.log"

    ai_text = read_text(ai_log, "")
    requests = ai_text.count("Request completed successfully")
    session_chars = count_chars(session_log)
    output_chars = count_chars(agent_out)

    input_tokens = int(session_chars * requests / 2 / CHARS_PER_TOKEN) if requests else 0
    output_tokens = int(output_chars / CHARS_PER_TOKEN)
    total_tokens = input_tokens + output_tokens

    return {
        "requests": requests,
        "session_chars": session_chars,
        "output_chars": output_chars,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def reward_value(reward):
    if reward in ("", None, "unknown"):
        return None
    try:
        return float(reward)
    except Exception:
        return None


def is_pass(reward):
    return reward_value(reward) == 1.0


def is_fail(reward):
    val = reward_value(reward)
    return val is not None and val != 1.0


def is_unknown(reward):
    return reward in ("", None, "unknown") or reward_value(reward) is None


def log_link(path):
    return f"`{path}`"


def generate(output_path=None):
    manifest = json.loads(read_text(MANIFEST_JSON, "{}"))
    metadata = json.loads(read_text(METADATA_JSON, "{}"))
    meta = manifest.pop("_meta", {}) if "_meta" in manifest else {}

    cases = []
    for key, item in manifest.items():
        name = item.get("name", key.split("/")[-1])
        version = item.get("version", "")
        md = metadata.get(name, {})
        domain = md.get("domain", item.get("domain", ""))
        difficulty = md.get("difficulty", item.get("difficulty", ""))
        tokens = estimate_tokens(name)
        cases.append({
            "order": item.get("order", 0),
            "key": key,
            "version": version,
            "name": name,
            "domain": domain,
            "difficulty": difficulty,
            "agent_status": item.get("agent_status", ""),
            "reward": item.get("reward", ""),
            "elapsed_sec": item.get("elapsed_sec", 0) or 0,
            "requests": tokens["requests"],
            "session_chars": tokens["session_chars"],
            "output_chars": tokens["output_chars"],
            "input_tokens": tokens["input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "total_tokens": tokens["total_tokens"],
            "result_dir": item.get("result_dir", str(RESULTS_DIR / name)),
        })

    cases.sort(key=lambda x: x["order"])
    total_cases = len(cases)
    completed_cases = sum(1 for c in cases if not is_unknown(c["reward"]))
    pass_cases = sum(1 for c in cases if is_pass(c["reward"]))
    fail_cases = sum(1 for c in cases if is_fail(c["reward"]))
    unknown_cases = sum(1 for c in cases if is_unknown(c["reward"]))
    reward_sum = sum(reward_value(c["reward"]) or 0.0 for c in cases)
    total_tokens = sum(c["total_tokens"] for c in cases)
    total_input_tokens = sum(c["input_tokens"] for c in cases)
    total_output_tokens = sum(c["output_tokens"] for c in cases)
    elapsed = meta.get("elapsed_sec", sum(c["elapsed_sec"] for c in cases))

    lines = []
    lines.append("# TB 2.1/3.0 Benchmark 数据报告\n")
    lines.append(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"> 模型：`{meta.get('model', 'unknown')}`\n")
    lines.append(f"> 运行起止：{meta.get('start_time', '-')} ~ {meta.get('end_time', '-')}\n")
    lines.append(f"> 总耗时：{format_elapsed(elapsed)}\n")
    lines.append("\n---\n")

    # 1. 综合打分
    lines.append("\n## 一、综合打分\n")
    lines.append("| 指标 | 数值 |")
    lines.append("| ---- | ---- |")
    lines.append(f"| 完成 case 数 / 总数 | {completed_cases} / {total_cases} |")
    lines.append(f"| 通过 case 数（reward=1） | {pass_cases} |")
    lines.append(f"| 失败 case 数 | {fail_cases} |")
    lines.append(f"| unknown case 数 | {unknown_cases} |")
    lines.append(f"| 总 reward | {reward_sum:.2f} / {total_cases} |")
    lines.append(f"| 通过率 | {pass_cases / total_cases * 100:.1f}% |")
    lines.append(f"| 估算输入 token | {total_input_tokens:,} |")
    lines.append(f"| 估算输出 token | {total_output_tokens:,} |")
    lines.append(f"| 估算总 token | {total_tokens:,} |")
    lines.append(f"| API 请求数 | {sum(c['requests'] for c in cases):,} |")
    lines.append(f"| 底层模型 | `{meta.get('model', 'unknown')}` |")
    lines.append("\n")

    # 2. 按版本维度
    lines.append("\n## 二、按版本维度\n")
    lines.append("| 版本 | 总数 | 通过 | 失败 | unknown | reward 和 | 估算总 token |")
    lines.append("| ---- | ----:| ----:| ----:| -------:| ---------:| -------------:|")
    for version in ["2.1", "3.0"]:
        subset = [c for c in cases if c["version"] == version]
        if not subset:
            continue
        lines.append(
            f"| {version} | {len(subset)} | "
            f"{sum(is_pass(c['reward']) for c in subset)} | "
            f"{sum(is_fail(c['reward']) for c in subset)} | "
            f"{sum(is_unknown(c['reward']) for c in subset)} | "
            f"{sum(reward_value(c['reward']) or 0.0 for c in subset):.2f} | "
            f"{sum(c['total_tokens'] for c in subset):,} |"
        )
    lines.append("\n")

    # 3. 按难度维度
    lines.append("\n## 三、按难度维度\n")
    lines.append("| 难度 | 总数 | 通过 | 失败 | unknown | reward 和 | 估算总 token |")
    lines.append("| ---- | ----:| ----:| ----:| -------:| ---------:| -------------:|")
    for diff in ["易", "中", "难"]:
        subset = [c for c in cases if c["difficulty"] == diff]
        if not subset:
            continue
        lines.append(
            f"| {diff} | {len(subset)} | "
            f"{sum(is_pass(c['reward']) for c in subset)} | "
            f"{sum(is_fail(c['reward']) for c in subset)} | "
            f"{sum(is_unknown(c['reward']) for c in subset)} | "
            f"{sum(reward_value(c['reward']) or 0.0 for c in subset):.2f} | "
            f"{sum(c['total_tokens'] for c in subset):,} |"
        )
    lines.append("\n")

    # 4. 详细结果（含中间日志）
    lines.append("\n## 四、详细结果\n")
    lines.append("| # | 版本 | 任务名 | 领域 | 难度 | 状态 | reward | 耗时 | 请求数 | 输入 token | 输出 token | 总 token | 日志 |")
    lines.append("|---|------|--------|------|------|------|--------|------|--------|------------|------------|----------|------|")
    for c in cases:
        result_dir = Path(c["result_dir"])
        log_links = " ".join([
            f"[session]({log_link(result_dir / 'session.log')})",
            f"[agent]({log_link(result_dir / 'agent_output.log')})",
            f"[verifier]({log_link(result_dir / 'verifier.log')})",
        ])
        reward_str = str(c["reward"]) if c["reward"] not in ("", None) else "unknown"
        lines.append(
            f"| {c['order']:02d} | {c['version']} | {c['name']} | {c['domain']} | {c['difficulty']} | "
            f"{c['agent_status']} | {reward_str} | {format_elapsed(c['elapsed_sec'])} | "
            f"{c['requests']} | {c['input_tokens']:,} | {c['output_tokens']:,} | {c['total_tokens']:,} | {log_links} |"
        )
    lines.append("\n")

    # 5. 每个 case 的运行中间结果（折叠）
    lines.append("\n## 五、Case 运行中间结果\n")
    lines.append(
        "以下按 case 展示最近日志片段，便于后续调优。输入 token 估算假设：未开启 compaction 时，"
        "每轮 prompt 都包含完整历史，因此累计输入 ≈ session_chars × requests / 2 / 4。\n"
    )
    for c in cases:
        result_dir = Path(c["result_dir"])
        session_text = read_text(result_dir / "session.log")
        agent_text = read_text(result_dir / "agent_output.log")
        verifier_text = read_text(result_dir / "verifier.log")
        session_tail = tail_lines(session_text, LOG_TAIL_LINES)
        agent_tail = tail_lines(agent_text, LOG_TAIL_LINES)
        verifier_tail = tail_lines(verifier_text, LOG_TAIL_LINES)

        lines.append(f"\n### {c['order']:02d}. {c['version']}/{c['name']}\n")
        lines.append(f"- 状态：{c['agent_status']} | reward：{c['reward']} | 耗时：{format_elapsed(c['elapsed_sec'])}\n")
        lines.append(f"- 请求数：{c['requests']} | 输入 token：{c['input_tokens']:,} | 输出 token：{c['output_tokens']:,} | 总 token：{c['total_tokens']:,}\n")
        lines.append("\n<details>\n<summary>session.log 最近 30 行</summary>\n\n```\n")
        lines.append(session_tail + "\n```\n\n</details>\n")
        lines.append("\n<details>\n<summary>agent_output.log 最近 30 行</summary>\n\n```\n")
        lines.append(agent_tail + "\n```\n\n</details>\n")
        lines.append("\n<details>\n<summary>verifier.log 最近 30 行</summary>\n\n```\n")
        lines.append(verifier_tail + "\n```\n\n</details>\n")

    report = "\n".join(lines)

    if output_path is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        output_path = RESULTS_DIR / f"benchmark_report_{ts}.md"
    else:
        output_path = Path(output_path)
    output_path.write_text(report, encoding="utf-8")
    print(f"Report written to {output_path}")
    return output_path


def format_elapsed(seconds):
    try:
        seconds = int(seconds)
    except Exception:
        return str(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    generate(out)
