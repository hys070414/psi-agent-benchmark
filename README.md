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

报告分七个章节：

| 章节 | 内容 |
|------|------|
| 一、综合打分 | 通过率、总 token、API 请求数等核心指标 |
| 二、按版本统计 | TB 2.1 / 3.0 分别的通过数、失败数、token 消耗 |
| 三、按难度统计 | 易/中/难的通过情况 |
| 四、按领域统计 | 各领域的通过情况 |
| 五、详细结果 | 每个 case 的状态、reward、耗时、token 明细及日志链接 |
| 六、Case 运行中间结果 | 每个 case 的 session/agent/verifier 日志尾部（折叠） |
| **七、错误分析** | **失败原因分类、工具调用统计、Skills/Tools 优化建议** |

### 错误分析详情

第七章自动解析每个失败 case 的日志，输出：

- **7.1 失败原因分类总览** — 按错误类别（轮次耗尽、编译错误、运行时错误、Verifier 拒绝、逻辑错误、环境错误、Agent 崩溃等）统计数量与占比，关联优化方向
- **7.2 各 Case 错误详情** — 每个 case 的具体错误原因、证据日志片段、该 case 的工具调用统计（调用次数/出错次数/错误率）
- **7.3 全局工具调用统计** — 汇总失败 case vs 通过 case 的各工具使用情况，识别高错误率工具
- **7.4 Skills/Tools 优化建议** — 基于错误分类和工具统计，按预期收益排序给出具体改进方向

这些分析直接指向 Agent 在通用 skills/tools 层面需要优化的环节，作为迭代改进的量化依据。

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
