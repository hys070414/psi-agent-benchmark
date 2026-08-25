# psi-agent-benchmark

Haitun（psi-agent）Terminal-Bench 一键评测工具。把 TB 2.1 / 3.0 的 case 推到远程服务器用 Docker 跑，跑完自动生成报告并下载到本地。

## 准备工作

- 一台装了 Docker 的境外 Linux 服务器（用户需在 docker 组）。
- 本机装 harbor：`pip install terminal-bench`。
- DeepSeek API Key 放在**服务器**的 `psi-agent/.env` 里，不在你本机。

## 三步跑起来

1. 克隆并进入目录：

```bash
git clone https://github.com/hys070414/psi-agent-benchmark.git
cd psi-agent-benchmark
```

2. 配置本机客户端（只管怎么连上服务器）：

```bash
cp .env.example .env
```

打开 `.env`，填服务器的 IP 和你本机的 SSH 私钥路径。这个文件只被 `trigger`/`fetch` 两个脚本读取，用来 SSH 进服务器，**不需要也不该放 DeepSeek Key**。

3. 跑评测并自动拿报告：

```bash
python bin/trigger_benchmark.py --cases 3.0/bun-sourcemap-leak --wait
```

`--wait` 会在服务器上跑完评测、生成报告，再把报告自动下载到本地 `reports/`。这就是完整闭环，中间不用你动手。

## 选哪些 case

不加筛选参数时，跑 `config/case_metadata.json` 里标记为 `enabled=true` 的 30 个。

| 参数 | 作用 |
|------|------|
| `--cases fix-git,caffe-cifar-10` | 精确指定，支持 `version/name` 或纯 name |
| `--versions 2.1,3.0` | 按版本筛 |
| `--difficulties 易,中,难` | 按难度筛 |
| `--exclude KEY` | 排除某个 case（可重复） |
| `--limit N` | 最多跑 N 个 |
| `--pick` | 交互式菜单，按版本分组选 |
| `--list` | 只列出将运行的 case，不执行 |

候选池来自 `config/case_metadata.json`。想换成官网全量（约 163 个）就跑 `python fetch_cases.py`，或直接编辑这个 JSON 增删、改难度。重新拉取时会保留已有的 `domain`/`difficulty`。

## 报告里有什么

每个 case 的状态、reward、请求数、token、日志片段，外加按版本 / 难度 / 领域的汇总，以及总通过率、总 token、总耗时。

评测已经跑完、只想单独拉报告时：

```bash
python bin/fetch_report.py
```

## 定时自动跑（可选）

在服务器上加 cron，每天自动评测并把报告路径写进 `LATEST_REPORT.txt`：

```cron
0 6 * * * cd /root/psi-agent-benchmark && bash bin/run_benchmark.sh >> pilot_results/cron.log 2>&1
```

别人配好自己机器的 `.env` 后，随时 `python bin/fetch_report.py` 就能取报告。想直接发到 GitHub，设 `GITHUB_TOKEN` 后跑 `bash bin/auto_bench.sh`，报告会推到独立的 `reports` 分支，不动 `main`。

## 目录

```text
├── case_metadata.json       # case 列表（唯一数据源）
├── config/benchmark.yaml    # 运行时参数
├── bin/
│   ├── trigger_benchmark.py # 本机触发远程评测 + 下载报告
│   ├── fetch_report.py      # 只拉最新报告
│   └── run_benchmark.sh     # 服务器一键运行
├── run_all_cases.py         # 评测主控
├── generate_report.py       # 报告生成
└── setup.sh                 # 服务器初始化
```
