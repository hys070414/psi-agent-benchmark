#!/usr/bin/env python3
"""P0/P1/P2 sandbox overlay builder for TB task images.

For each image:
  (1) Write a short Dockerfile at build dir
  (2) `docker build -t tb-X.Y-<name>:overlay-c1 .` — applies apt/pip/data layers
  (3) re-tag overlay-c1 as :latest so benchmark uses it.

Also runs a quick sanity check in a throwaway container.

Priority tiers (from Run3 failure root-cause analysis):
  P0 = must-fix (env hard-failures, agent can't even start)
  P1 = high-ROI (env slows down agent or causes timeout)
  P2 = optional nice-to-haves
"""
import os, sys, subprocess, json, time
from pathlib import Path

WORKDIR = Path(os.path.expanduser("~/psi-agent-benchmark"))
BUILD = WORKDIR / "_sandbox_overlay_builds"
BUILD.mkdir(exist_ok=True)

# ============================================================
# OVERLAY CONFIGURATION
# ============================================================
# Each entry:
#   base_tag   - source image to layer on top of
#   new_tag    - output image tag
#   apt        - (optional) space-separated apt packages to install
#   pip        - (optional) space-separated pip packages to install
#   pre        - (optional) shell commands to run before apt (e.g. add repos)
#   post       - (optional) shell commands to run after apt/pip (e.g. download datasets)
#   sanity_cmds - (optional) list of commands to verify in sanity check
# ============================================================

OVERLAYS = {
    # ========================================================
    # P0 — 纯环境卡死，不修必挂（3 个 case）
    # ========================================================

    "largest-eigenval": {
        "base_tag": "tb-2.1-largest-eigenval:latest",
        "new_tag":  "tb-2.1-largest-eigenval:overlay-c1",
        "priority": "P0",
        "apt": (
            "gcc build-essential binutils gfortran "
            "libopenblas-dev liblapack-dev"
        ),
        "pip": "scipy numpy",
        "sanity_cmds": ["gcc", "gfortran", "python3", "pip3"],
    },

    "polyglot-c-py": {
        "base_tag": "tb-2.1-polyglot-c-py:latest",
        "new_tag":  "tb-2.1-polyglot-c-py:overlay-c1",
        "priority": "P0",
        "apt": "python3 python3-pip python3-venv gcc",
        "sanity_cmds": ["python3", "pip3", "gcc"],
    },

    "install-windows-3.11": {
        "base_tag": "tb-2.1-install-windows-3.11:latest",
        "new_tag":  "tb-2.1-install-windows-3.11:overlay-c1",
        "priority": "P0",
        "apt": (
            "qemu-system-x86 qemu-system-gui qemu-utils "
            "seabios vgabios libcapstone4 libxen-4.14 libvdeplug2 "
            "libjpeg62-turbo liburing1 libaio1 "
            "curl socat netcat-openbsd "
            "tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu tesseract-ocr-chi-sim"
        ),
        "sanity_cmds": ["qemu-system-i386", "curl", "socat", "tesseract"],
    },

    # ========================================================
    # P1 — 改善率高，节省 agent turns / 避免超时
    # ========================================================

    # --- 2.1 cases ---

    "caffe-cifar-10": {
        "base_tag": "tb-2.1-caffe-cifar-10:latest",
        "new_tag":  "tb-2.1-caffe-cifar-10:overlay-c1",
        "priority": "P1",
        "apt": "curl ca-certificates file xz-utils zip unzip",
        "pip": "numpy protobuf",
        # Pre-download CIFAR-10 binary dataset to /opt/datasets/
        "post": (
            "mkdir -p /opt/datasets && "
            "cd /opt/datasets && "
            "curl -fsSL -o cifar-10-binary.tar.gz "
            "  https://www.cs.toronto.edu/~kriz/cifar-10-binary.tar.gz && "
            "tar xzf cifar-10-binary.tar.gz && "
            "rm cifar-10-binary.tar.gz && "
            "ls -la /opt/datasets/cifar-10-batches-bin/"
        ),
        "sanity_cmds": ["python3", "curl", "file"],
    },

    "chess-best-move": {
        "base_tag": "tb-2.1-chess-best-move:latest",
        "new_tag":  "tb-2.1-chess-best-move:overlay-c1",
        "priority": "P1",
        "apt": "file xz-utils",
        "pip": "numpy chess Pillow",
        "sanity_cmds": ["python3", "stockfish"],
    },

    # --- 3.0 cases ---

    "foodstuff-beta-activity": {
        "base_tag": "tb-3.0-foodstuff-beta-activity:latest",
        "new_tag":  "tb-3.0-foodstuff-beta-activity:overlay-c1",
        "priority": "P1",
        "apt": "file poppler-utils xz-utils zip unzip ca-certificates",
        "pip": "pandas xlrd openpyxl pypdf pdfplumber numpy",
        "sanity_cmds": ["python3", "file", "pdftotext"],
    },

    "freecad-platform-drawing": {
        "base_tag": "tb-3.0-freecad-platform-drawing:latest",
        "new_tag":  "tb-3.0-freecad-platform-drawing:overlay-c1",
        "priority": "P1",
        "apt": "file python3-pil xz-utils zip unzip",
        "pip": "numpy Pillow opencv-python",
        "sanity_cmds": ["python3", "freecad", "file"],
    },

    "interleaved-vigenere": {
        "base_tag": "tb-3.0-interleaved-vigenere:latest",
        "new_tag":  "tb-3.0-interleaved-vigenere:overlay-c1",
        "priority": "P1",
        "apt": "file xz-utils",
        "pip": "numpy",
        "sanity_cmds": ["python3"],
    },

    "atrx-vep-crispr": {
        "base_tag": "tb-3.0-atrx-vep-crispr:latest",
        "new_tag":  "tb-3.0-atrx-vep-crispr:overlay-c1",
        "priority": "P1",
        "apt": (
            "file xz-utils zip unzip ca-certificates "
            "perl cpanminus build-essential"
        ),
        # Install Bio::EnsEMBL::Registry via cpanm + download chrX GRCh38 FASTA
        "post": (
            "cpanm --notest Bio::EnsEMBL::Registry 2>&1 | tail -5; "
            "mkdir -p /opt/datasets/GRCh38 && "
            "cd /opt/datasets/GRCh38 && "
            "curl -fsSL -o chrX.fa.gz "
            "  http://ftp.ensembl.org/pub/release-112/fasta/homo_sapiens/dna/Homo_sapiens.GRCh38.dna.chromosome.X.fa.gz && "
            "gunzip chrX.fa.gz && "
            "ls -la /opt/datasets/GRCh38/chrX.fa"
        ),
        "pip": "numpy",
        "sanity_cmds": ["python3", "vep", "perl"],
    },

    "live-database-cutover": {
        "base_tag": "tb-3.0-live-database-cutover:latest",
        "new_tag":  "tb-3.0-live-database-cutover:overlay-c1",
        "priority": "P1",
        # Use Debian native mariadb-server to avoid expired MySQL APT GPG key
        "apt": (
            "mariadb-server mariadb-client "
            "file procps psmisc xz-utils zip unzip ca-certificates "
            "postgresql postgresql-client python3-psycopg2"
        ),
        "pip": "mysql-connector-python sqlalchemy psycopg2-binary",
        "sanity_cmds": ["mariadb", "psql", "python3", "ps"],
    },

    "medical-claims-processing": {
        "base_tag": "tb-3.0-medical-claims-processing:latest",
        "new_tag":  "tb-3.0-medical-claims-processing:overlay-c1",
        "priority": "P1",
        # Note: the main issue is orchestration (workspace service not mounted),
        # but we still pre-install pip deps to save turns
        "apt": "file procps psmisc curl ca-certificates xz-utils zip unzip",
        "pip": "numpy opencv-python flask flask-cors pyyaml pandas",
        "sanity_cmds": ["python3", "curl"],
    },

    "satb-audio-transcription": {
        "base_tag": "tb-3.0-satb-audio-transcription:latest",
        "new_tag":  "tb-3.0-satb-audio-transcription:overlay-c1",
        "priority": "P1",
        "apt": "file xz-utils zip unzip ca-certificates",
        "pip": "numpy matplotlib librosa soundfile",
        "sanity_cmds": ["python3", "ffmpeg"],
    },

    "gpt2-codegolf": {
        "base_tag": "tb-3.0-gpt2-codegolf:latest",
        "new_tag":  "tb-3.0-gpt2-codegolf:overlay-c1",
        "priority": "P1",
        "apt": "file xz-utils zip unzip ca-certificates",
        "pip": "numpy",
        "sanity_cmds": ["gcc", "python3"],
    },

    "retro-console-soc": {
        "base_tag": "tb-3.0-retro-console-soc:latest",
        "new_tag":  "tb-3.0-retro-console-soc:overlay-c1",
        "priority": "P1",
        "apt": "file python3-pip xz-utils zip unzip ca-certificates",
        "pip": "numpy",
        "sanity_cmds": ["python3", "pip3", "verilator"],
    },

    "vllm-deepseek-streaming": {
        "base_tag": "tb-3.0-vllm-deepseek-streaming:latest",
        "new_tag":  "tb-3.0-vllm-deepseek-streaming:overlay-c1",
        "priority": "P1",
        "apt": "git openssh-client ca-certificates file xz-utils zip unzip patch diffutils",
        "sanity_cmds": ["git", "python3"],
    },

    # ========================================================
    # Already done / verified overlays
    # ========================================================

    "fix-git": {
        "base_tag": "tb-2.1-fix-git:latest",
        "new_tag":  "tb-2.1-fix-git:overlay-c1",
        "priority": "Done",
        "apt": "curl ca-certificates openssh-client patch diffutils procps less file xz-utils",
        "sanity_cmds": ["bash", "python3", "git", "curl"],
    },

    "bun-sourcemap-leak": {
        "base_tag": "tb-3.0-bun-sourcemap-leak:latest",
        "new_tag":  "tb-3.0-bun-sourcemap-leak:overlay-c1",
        "priority": "Done",
        "pre": (
            "apt-get update && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
            "ca-certificates curl gnupg sudo apt-transport-https lsb-release software-properties-common && "
            "mkdir -p /etc/apt/keyrings && "
            "curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key "
            "  | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && "
            "echo 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main' "
            "  > /etc/apt/sources.list.d/nodesource.list && "
            "apt-get update"
        ),
        "apt": (
            "git openssh-client nodejs ca-certificates procps less file xz-utils "
            "patch diffutils zip unzip"
        ),
        "sanity_cmds": ["bun", "node", "npm", "git", "curl"],
    },
}


def run(cmd: str, timeout=1800, check=True, env=None):
    print(f"\n$ {cmd[:200]}")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=env)
    if r.stdout.strip():
        for ln in r.stdout.strip().splitlines()[-30:]:
            print(f"  {ln}")
    if r.stderr.strip():
        for ln in r.stderr.strip().splitlines()[-30:]:
            print(f"  [err] {ln}")
    print(f"  rc={r.returncode}")
    if check and r.returncode != 0:
        raise RuntimeError(f"Command FAILED: {cmd[:120]}... rc={r.returncode}")
    return r


def build(task: str):
    cfg = OVERLAYS[task]
    tag_dir = BUILD / task
    tag_dir.mkdir(exist_ok=True)

    # Build Dockerfile content
    dockerfile = f"FROM {cfg['base_tag']}\n"
    dockerfile += "ENV DEBIAN_FRONTEND=noninteractive\n"

    # Pre-install commands (e.g. add repos)
    if "pre" in cfg and cfg["pre"]:
        dockerfile += f"RUN set -eux; {cfg['pre']} 2>&1 | tail -n 80\n"

    # apt packages
    if "apt" in cfg and cfg["apt"]:
        dockerfile += (
            f"RUN set -eux; "
            f"apt-get update && "
            f"apt-get install -y --no-install-recommends {cfg['apt']} 2>&1 | tail -n 40 && "
            f"rm -rf /var/lib/apt/lists/*\n"
        )

    # pip packages
    if "pip" in cfg and cfg["pip"]:
        dockerfile += (
            f"RUN set -eux; "
            f"pip3 install --no-cache-dir --break-system-packages {cfg['pip']} 2>&1 | tail -n 20\n"
        )

    # Post-install commands (e.g. download datasets)
    if "post" in cfg and cfg["post"]:
        dockerfile += f"RUN set -eux; {cfg['post']} 2>&1 | tail -n 40\n"

    # Sanity check in Dockerfile
    sanity = cfg.get("sanity_cmds", ["bash", "python3"])
    sanity_checks = " && ".join([f"command -v {c} >/dev/null" for c in sanity])
    dockerfile += f"RUN set -eux; {sanity_checks}\n"

    (tag_dir / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"  Building overlay for {task} (priority: {cfg.get('priority', '?')})")
    print(f"  Base: {cfg['base_tag']}")
    print(f"  Output: {cfg['new_tag']}")
    print(f"{'='*60}")
    print(f"\nDockerfile:\n")
    print(dockerfile)

    # Build
    run(f"docker build --no-cache -t {cfg['new_tag']} -f {tag_dir}/Dockerfile {tag_dir} 2>&1", timeout=1800)

    # Retag :latest → overlay-c1 so benchmark uses the patched image
    run(f"docker tag {cfg['new_tag']} {cfg['base_tag']}")

    # Quick sanity in a throwaway container
    print(f"\n--- Quick sanity for {task} overlay ---")
    cname = f"sbx-ovl-{task}-{int(time.time())}"
    verify_cmds = sanity + ["python3"]
    try:
        cmd = (
            f"docker run --rm --name {cname} {cfg['new_tag']} bash -lc '"
            f"echo ===which===; "
            + " ".join([f"command -v {c} >/dev/null && echo {c} OK || echo {c} MISSING;" for c in verify_cmds])
            + "echo ===versions===; "
            + "python3 --version 2>&1; "
            + "pip3 --version 2>&1 || true; "
            + "gcc --version 2>&1 | head -1 || true; "
            + "git --version 2>&1 || true; "
            + "curl --version 2>&1 | head -1 || true"
            + "'"
        )
        run(cmd, timeout=180)
    except Exception as e:
        print(f"  sanity non-fatal: {e}")

    print(f"  ✓ {task} overlay done")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build TB sandbox overlay images")
    parser.add_argument("tasks", nargs="*", help="Specific tasks to build (default: all P0+P1)")
    parser.add_argument("--p0", action="store_true", help="Build only P0 (critical)")
    parser.add_argument("--p1", action="store_true", help="Build only P1 (high ROI)")
    parser.add_argument("--all", action="store_true", help="Build all overlays including done ones")
    parser.add_argument("--list", action="store_true", help="List available overlays and exit")
    args = parser.parse_args()

    if args.list:
        print("Available overlays:")
        for name, cfg in sorted(OVERLAYS.items()):
            pri = cfg.get("priority", "?")
            print(f"  [{pri}] {name}")
        print()
        print(f"Total: {len(OVERLAYS)} overlays")
        return

    # Determine which tasks to build
    if args.tasks:
        tasks = args.tasks
        # Validate
        for t in tasks:
            if t not in OVERLAYS:
                print(f"ERROR: unknown task '{t}'")
                print(f"Available: {', '.join(sorted(OVERLAYS.keys()))}")
                sys.exit(1)
    elif args.p0:
        tasks = [n for n, c in OVERLAYS.items() if c.get("priority") == "P0"]
    elif args.p1:
        tasks = [n for n, c in OVERLAYS.items() if c.get("priority") == "P1"]
    elif args.all:
        tasks = list(OVERLAYS.keys())
    else:
        # Default: P0 + P1 (the actionable ones)
        tasks = [n for n, c in OVERLAYS.items() if c.get("priority") in ("P0", "P1")]

    print(f"Building {len(tasks)} overlay(s): {', '.join(tasks)}")
    print()

    failed = []
    for i, task in enumerate(tasks, 1):
        print(f"\n\n{'#'*60}")
        print(f"# [{i}/{len(tasks)}] {task}")
        print(f"{'#'*60}")
        try:
            build(task)
        except Exception as e:
            print(f"\n  ✗ FAILED: {e}")
            failed.append(task)

    # Summary
    print(f"\n\n{'='*60}")
    print(f"  BUILD SUMMARY")
    print(f"{'='*60}")
    print(f"  Total:  {len(tasks)}")
    print(f"  OK:     {len(tasks) - len(failed)}")
    print(f"  Failed: {len(failed)}")
    if failed:
        print(f"  Failed tasks: {', '.join(failed)}")
    print()

    # List resulting images
    print("Resulting images:")
    for task in tasks:
        cfg = OVERLAYS[task]
        r = run(
            f"docker images --format '{{{{.Repository}}}}:{{{{.Tag}}}} {{{{.ID}}}}' "
            f"| grep -E '^{cfg['base_tag'].split(':')[0]}(:latest|:overlay)'",
            check=False
        )
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                print(f"  {line}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
