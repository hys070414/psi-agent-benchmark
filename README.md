# psi-agent-benchmark

Haitun（psi-agent）Terminal-Bench 一键评测工具。

## 快速开始

### 前置条件

- 一台境外 Linux 服务器（≥4vCPU/16GB/200GB，安装 Docker 且用户需在 docker 组）
- `harbor` CLI：`pip install terminal-bench`
- DeepSeek API Key

### 1. 克隆

```bash
git clone https://github.com/hys070414/psi-agent-benchmark.git
cd psi-agent-benchmark
```

### 2. 配置

```bash
cp .env.example .env
vim .env
```

必填项：

| 变量 | 说明 |
|------|------|
| `TB_BENCH_HOST` | 评测服务器 IP |
| `TB_BENCH_USER` | 评测服务器用户名 |
| `TB_BENCH_PASSWORD` 或 `TB_BENCH_KEY` | 密码或 SSH 私钥路径 |
| `TB_BENCH_WORKDIR` | 服务器工作目录 |
| `PSI_AI_API_KEY` | DeepSeek API Key |

### 3. 一键评测

```bash
# 测试主分支 — 跑所有 enabled 的 case
python bin/trigger_benchmark.py --branch main --wait

# 测试指定分支
python bin/trigger_benchmark.py --branch feature-xxx --wait
```

### Case 自由选择

候选池默认来自 `config/case_metadata.json`。该文件**由官网仓库自动拉取生成**（不再手写）：

- TB 2.1 官方仓库：`harbor-framework/terminal-bench-2-1`
- TB 3.0 官方仓库：`dataforasi/terminal-bench-3-public`（官方开发镜像）

**方式零：从官网拉取全量 case（推荐先跑一次）**

```bash
# 仅拉取 case 名称（约 2 次 API 调用，无需 token）
python fetch_cases.py

# 同时补全每个 task 的 difficulty / domain（需 GitHub token，否则易限流）
GITHUB_TOKEN=ghp_xxx python fetch_cases.py --with-meta

# 自定义 3.0 数据源（官方仓库发布后在此替换）
python fetch_cases.py --3.0-repo owner/repo
```

`fetch_cases.py` 会把 TB 2.1 / 3.0 的**全部** case 写入 `config/case_metadata.json`，
并保留旧文件中已有的 difficulty / domain。当前共约 163 个 case（2.1: 89，3.0: 74）。

**默认行为与候选池的关系：**
- 候选池里有 **163 个** case，但只有最初的精选 **30 个** 标记为 `enabled=true`。
- 不带任何筛选参数直接跑 → 只执行这 30 个（与改造前行为一致）。
- 其余 133 个并非消失，而是作为**可选项**存在：通过 `--pick` 菜单、`--cases`、`--versions`、`--difficulties` 等显式筛选时，会从全部 163 个里自由选择，不受 `enabled` 限制。
- `fetch_cases.py` / `--refresh` 重新拉取官网清单时，会始终保持这 30 个为默认启用、其余为可选（除非用 `--with-meta` 补全元数据）。

跑评测前也可直接在服务器上刷新候选池：

```bash
python3 run_all_cases.py --refresh            # 刷新名称
python3 run_all_cases.py --refresh --refresh-meta   # 刷新并补全元数据（需 GITHUB_TOKEN）
```

**方式一：交互式选择（推荐）**

```bash
# 本地弹菜单 → 选中后自动触发远程评测
python bin/trigger_benchmark.py --pick --wait
```

菜单按 TB 2.1 / TB 3.0 分组列出全部 case，输入编号即可挑选：

```text
─── TB 2.1（89 个）───
   1. caffe-cifar-10                中   Machine Learning
   2. chess-best-move               中   Games
   ...
─── TB 3.0（74 个）───
  90. atrx-vep-crispr               中   Science（Biology）
  91. bun-sourcemap-leak            易   Software（Systems）
  ...

输入编号选择（示例: 1,3-5,12  或  2.1  或  3.0  或  a 全选，q 放弃）:
```

支持 `1,3,5` 逗号单选、`2-6` 区间（可跨版本）、`2.1` / `3.0` 整版本、`a` 全选。

**方式二：命令行参数**

```bash
# 只跑指定 case（逗号分隔，支持 "version/name" 或纯 name）
python bin/trigger_benchmark.py --cases fix-git,caffe-cifar-10 --wait

# 只跑 TB 2.1 版本
python bin/trigger_benchmark.py --versions 2.1 --wait

# 只跑 TB 3.0 容易+中等难度
python bin/trigger_benchmark.py --versions 3.0 --difficulties 易,中 --wait

# 排除指定 case
python bin/trigger_benchmark.py --exclude "2.1/fix-git" --wait

# 限制最多跑 5 个
python bin/trigger_benchmark.py --limit 5 --wait
```

**方式三：在远程服务器上直接运行**

```bash
# 交互式选择（服务器上直接跑）
python3 run_all_cases.py --pick

# 通过环境变量传参
TB_CASE_ARGS="--versions 2.1 --difficulties 易" bash run_benchmark.sh

# 直接调用 run_all_cases.py
python3 run_all_cases.py --versions 2.1 --difficulties 易 --limit 5

# 列出将运行的 case（不执行评测）
python3 run_all_cases.py --versions 3.0 --list
```

筛选优先级：`--pick` / `--cases` > `--versions` / `--difficulties` / `--exclude` > `benchmark.yaml` 的 `case_filter`。

| 参数 | 说明 |
|------|------|
| `--pick` / `-p` | 交互式选择：按 TB 2.1/3.0 分组展示，输入编号挑选 |
| `--refresh` | 运行前从官网拉取 TB 2.1/3.0 全量 case，刷新候选池 |
| `--refresh-meta` | 配合 `--refresh`，同时补全 task.toml 的 difficulty/domain（需 GITHUB_TOKEN） |
| `--cases NAME1,NAME2` | 精确指定 case，忽略版本/难度筛选 |
| `--versions 2.1,3.0` | 版本筛选 |
| `--difficulties 易,中,难` | 难度筛选 |
| `--exclude KEY` | 排除指定 case（可多次使用） |
| `--limit N` | 最多运行 N 个 case |
| `--list` | 列出将运行的 case 后退出 |

### 4. 查看报告

跑评测用 `--wait` 时，脚本会**自动**等待评测完成、生成报告并下载到本地 `reports/` 目录：

```bash
python bin/trigger_benchmark.py --cases fix-git,caffe-cifar-10 --wait
# 跑完后 reports/benchmark_report_*.md 即为本次报告
```

链路说明（评测结束 → 自动出报告 → 自动下载，无需人工干预）：

1. `run_benchmark.sh` 在服务器 tmux 中跑 `run_all_cases.py`，随后调用 `generate_report.py`；
2. `generate_report.py` 把报告写入 `pilot_results/benchmark_report_<时间戳>.md`，并把**裸路径**写入 `pilot_results/LATEST_REPORT.txt`；
3. `trigger_benchmark.py --wait` 轮询 `LATEST_REPORT.txt`，读到 `.md` 路径后自动 SFTP 下载到本地 `reports/`。

若评测已跑完、只想单独拉取最新报告：

```bash
python bin/fetch_report.py
```

报告包含：

- 综合打分（完成数/总数、通过率、token 消耗、耗时）
- 按版本/难度/领域维度统计
- 每个 Case 的详细结果（状态、reward、请求数、token、日志片段）

## 全无人值守（可选）

如果希望**无需任何手动触发**就定期出报告，可在评测服务器上用 cron / systemd 定时跑 `run_benchmark.sh`。它所写出的 `LATEST_REPORT.txt` 即为本次报告路径，其他人可用 `python bin/fetch_report.py`（任意机器、配好 `.env`）随时拉取；或让服务器把报告发布到可访问的位置。

**cron 示例（每天 06:00 跑一次）：**

```cron
0 6 * * * cd /root/psi-agent-benchmark && bash bin/run_benchmark.sh >> pilot_results/cron.log 2>&1
```

**一键无人值守 + 自动发布到仓库（可选）：**

`bin/auto_bench.sh` 在 `run_benchmark.sh` 基础上，等报告生成后把最新报告复制进 `reports/`，并在提供 `GITHUB_TOKEN` 时推送到仓库的 `reports` 分支，这样他人无需登录服务器即可在 GitHub 上看到报告：

```bash
# 仅本地生成 + 写出 LATEST_REPORT.txt
bash bin/auto_bench.sh

# 额外把报告推送到仓库 reports 分支（他人可直接在 GitHub 查看）
GITHUB_TOKEN=ghp_xxx bash bin/auto_bench.sh
```

> 注意：自动推送默认写到独立的 `reports` 分支，不会动 `main` 分支，避免覆盖你的代码。

## 自定义 Case 列表

候选池由 `fetch_cases.py` / `--refresh` 从官网生成并写入 `case_metadata.json`。
如需**永久**增删或改难度，直接编辑该 JSON 的对应条目即可；若重新运行 `fetch_cases.py`
或 `--refresh`，程序会保留旧条目已有的 `domain` / `difficulty`（按 `version/name` 合并，不会清空）。

临时跳过某个 Case，设置 `"enabled": false`：

```json
{
  "2.1/caffe-cifar-10": {
    "version": "2.1",
    "name": "caffe-cifar-10",
    "domain": "Machine Learning",
    "difficulty": "中",
    "enabled": false
  }
}
```

## 目录结构

```text
├── case_metadata.json       # Case 列表（唯一数据源）
├── config/benchmark.yaml    # 运行时参数
├── bin/
│   ├── trigger_benchmark.py # 本地触发远程评测
│   ├── fetch_report.py      # 拉取报告
│   └── run_benchmark.sh     # 远程一键运行
├── setup.sh                 # 服务器环境初始化
├── build_images.sh          # 自动构建 Docker 镜像
├── run_all_cases.py         # 评测主控
└── generate_report.py       # 生成数据报告
```