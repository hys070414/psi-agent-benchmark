#!/usr/bin/env python3
"""从 Terminal-Bench 官网仓库拉取 TB 2.1 / 3.0 的全部 case 清单。

设计要点：
- 仅用标准库（urllib + base64），不引入第三方依赖。
- 数据源为 GitHub 上两个官方仓库的 `tasks/` 目录，每个子目录即一个 case，
  其名称与 `harbor task download terminal-bench/{name}` 完全对应。
- 默认只拉取 case 名称（2 次 API 调用），`--with-meta` 时再逐个抓取 task.toml
  解析 difficulty / category（需要 GitHub token，否则易触发匿名限流）。

输出格式与现有 config/case_metadata.json 兼容：以 "version/name" 为键。
"""

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com"

# 官方数据源。3.0 目前以官方开发镜像仓库为准（harbor-framework/terminal-bench-3
# 尚未公开发布），如日后官方仓库地址变更，改这里即可。
DEFAULT_SOURCES = {
    "2.1": {"owner": "harbor-framework", "repo": "terminal-bench-2-1", "branch": None},
    "3.0": {"owner": "dataforasi", "repo": "terminal-bench-3-public", "branch": None},
}

# task.toml 里 difficulty 是英文，映射到中文便于展示
DIFF_MAP = {
    "easy": "易",
    "medium": "中",
    "hard": "难",
    "trivial": "易",
    "expert": "难",
}

# 默认启用的 case（最初的精选 30 个）。只有这些 enabled=true，其余全量 case
# 仅作为可选项出现在 --pick 菜单 / --versions / --cases 中，不会被默认跑。
# 重新拉取官网清单（fetch_cases.py / run_all_cases.py --refresh）时此集合始终保留。
DEFAULT_ENABLED_KEYS = frozenset({
    "2.1/caffe-cifar-10",
    "2.1/chess-best-move",
    "2.1/cobol-modernization",
    "2.1/configure-git-webserver",
    "2.1/crack-7z-hash",
    "2.1/db-wal-recovery",
    "2.1/filter-js-from-html",
    "2.1/fix-git",
    "2.1/install-windows-3.11",
    "2.1/largest-eigenval",
    "2.1/llm-inference-batching-scheduler",
    "2.1/overfull-hbox",
    "2.1/polyglot-c-py",
    "2.1/prove-plus-comm",
    "2.1/rstan-to-pystan",
    "3.0/atrx-vep-crispr",
    "3.0/bun-sourcemap-leak",
    "3.0/fin-saccr-rwa",
    "3.0/foodstuff-beta-activity",
    "3.0/freecad-platform-drawing",
    "3.0/gpt2-codegolf",
    "3.0/interleaved-vigenere",
    "3.0/live-database-cutover",
    "3.0/medical-claims-processing",
    "3.0/music-harmony",
    "3.0/photonic-waveguide-routing",
    "3.0/retro-console-soc",
    "3.0/satb-audio-transcription",
    "3.0/takens-embedding-lean",
    "3.0/vllm-deepseek-streaming",
})


def _api_get(url, token=None):
    """调用 GitHub API，返回解析后的 JSON。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "tb-case-fetch",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def get_default_branch(owner, repo, token=None):
    data = _api_get(f"{GITHUB_API}/repos/{owner}/{repo}", token)
    return data.get("default_branch", "main")


def list_task_names(owner, repo, token=None):
    """列出某仓库 tasks/ 下的全部 case 名称（目录名）。"""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/tasks?per_page=300"
    data = _api_get(url, token)
    if isinstance(data, dict):
        raise RuntimeError(data.get("message", "unknown error"))
    return sorted(x["name"] for x in data if x.get("type") == "dir")


def get_task_metadata(owner, repo, branch, name, token=None):
    """抓取单个 task 的 task.toml，解析 [metadata] 下的 difficulty / category。"""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/tasks/{name}/task.toml"
    try:
        data = _api_get(url, token)
    except urllib.error.HTTPError:
        return {}
    if isinstance(data, dict) and "content" in data:
        content = base64.b64decode(data["content"]).decode("utf-8", "replace")
        return parse_task_toml_metadata(content)
    return {}


def parse_task_toml_metadata(text):
    """极简 TOML 解析，仅提取 [metadata] 段落的 difficulty / category / subcategory。"""
    difficulty = None
    category = None
    subcategory = None
    in_meta = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_meta = line == "[metadata]"
            continue
        if not in_meta or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "difficulty":
            difficulty = val
        elif key == "category":
            category = val
        elif key == "subcategory":
            subcategory = val
    out = {}
    if difficulty:
        out["difficulty"] = DIFF_MAP.get(difficulty.lower(), difficulty)
    if category:
        # "software-engineering" -> "Software Engineering"
        domain = " ".join(w.capitalize() for w in category.replace("-", " ").split())
        if subcategory:
            sub = " ".join(w.capitalize() for w in subcategory.replace("-", " ").split())
            domain = f"{domain}（{sub}）"
        out["domain"] = domain
    return out


def build_case_metadata(token=None, with_meta=False, sources=None, log=print):
    """从官网拉取全量 case 清单，返回 {version/name: {version,name,domain,difficulty,enabled}}。"""
    sources = sources or DEFAULT_SOURCES
    result = {}
    for version, cfg in sources.items():
        owner = cfg["owner"]
        repo = cfg["repo"]
        try:
            names = list_task_names(owner, repo, token)
        except Exception as e:
            log(f"WARN: 无法拉取 TB {version} 任务列表（{owner}/{repo}）: {e}")
            continue
        branch = cfg.get("branch") or get_default_branch(owner, repo, token)
        log(f"TB {version}: 从 {owner}/{repo}@{branch} 拉取 {len(names)} 个 case")
        for name in names:
            key = f"{version}/{name}"
            entry = {
                "version": version,
                "name": name,
                "domain": "",
                "difficulty": "",
                "enabled": key in DEFAULT_ENABLED_KEYS,
            }
            if with_meta:
                try:
                    entry.update(get_task_metadata(owner, repo, branch, name, token))
                except Exception as e:
                    log(f"  (跳过 {name} 元数据: {e})")
            result[f"{version}/{name}"] = entry
    return result


def merge_existing(result, existing):
    """用旧文件中已有的 domain/difficulty 回填新拉取的条目（按 version/name 匹配）。"""
    old_by_key = {}
    for key, val in existing.items():
        # 兼容旧版“仅按 name 键”的文件
        if "/" in key:
            old_by_key[key] = val
        else:
            old_by_key[f"{val.get('version', '')}/{key}"] = val
    for key, entry in result.items():
        old = old_by_key.get(key)
        if not old:
            continue
        for field in ("domain", "difficulty"):
            if old.get(field) and not entry.get(field):
                entry[field] = old[field]
    return result


def refresh_case_metadata(path, token=None, with_meta=False, sources=None, log=print):
    """拉取最新清单并与现有文件合并后写回。返回最终 case 数。"""
    path = Path(path)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"WARN: 读取现有 {path} 失败，将用官网数据覆盖: {e}")
    fresh = build_case_metadata(token=token, with_meta=with_meta, sources=sources, log=log)
    fresh = merge_existing(fresh, existing)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return len(fresh)
