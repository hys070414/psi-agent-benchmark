# TB-Bench × psi-agent 一键评测仓库

面向同一团队开发者的可复现 Terminal-Bench 2.1/3.0 自动化 benchmark 仓库。

***

## 仓库结构

```
.
├── README.md
├── .env.example              # 环境变量模板
├── requirements.txt          # 本地依赖
├── setup.sh                  # 服务器端初始化脚本
├── config/
│   └── benchmark.yaml        # case 列表、模型、超时配置
├── bin/
│   ├── trigger_benchmark.py  # 本地一键触发远程 benchmark
│   ├── fetch_report.py       # 拉取服务器最新报告到本地
│   └── run_benchmark.sh      # 服务器端一键运行脚本
├── run_all_cases.py          # benchmark 主控（改编自 psi-agent）
├── generate_report.py        # 自动生成数据-only 报告
└── case_metadata.json        # 30 case 的版本/领域/难度元数据
```

***

## 前置条件

- 一台境外 Linux 服务器（推荐 ≥4 vCPU / 16 GB / 200 GB SSD）
- Docker 已安装并可用
- Python 3.10+
- Git
- 大模型 API key（当前配置为 deepseek-v4-flash）

***

## 快速开始

### 1. 克隆仓库到服务器

```bash
git clone <your-repo-url> /root/tb-bench-psi-agent
cd /root/tb-bench-psi-agent
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 API key、服务器密码等真实值
```

### 3. 初始化

```bash
bash setup.sh
```

这会：
- 安装 Python 依赖
- 拉取/更新 psi-agent
- 将本仓库脚本复制到 psi-agent 目录
- 创建 `$TB_BENCH_WORKDIR/.env`

### 4. 构建 case 镜像

> 第一次运行前，需要为 30 个 case 分别构建 Docker 镜像。

```bash
cd /root/haitun-tb/psi-agent
python3 make_pilot_workspace.py  # 如已有镜像构建脚本，请替换为实际命令
```

### 5. 一键运行 benchmark

**在服务器上直接运行：**

```bash
bash /root/haitun-tb/psi-agent/run_benchmark.sh
```

**在本地 Windows 触发：**

```powershell
cd C:\Users\hwm20\OneDrive\桌面\tb\tb-bench-psi-agent
python bin\trigger_benchmark.py
```

触发后，benchmark 会在服务器 tmux 会话中后台运行，跑完自动生成报告。

**拉取最新报告到本地：**

```powershell
python bin\fetch_report.py
```

报告会保存到 `reports/benchmark_report_<timestamp>.md`。

***

## 查看进度

SSH 到服务器后：

```bash
tmux attach -t tb-bench-<timestamp>
# 或看状态文件
cat /root/haitun-tb/pilot_results/benchmark_status.txt
```

***

## 报告产出

跑完后，最新报告路径会写入：

```text
/root/haitun-tb/pilot_results/LATEST_REPORT.txt
```

报告内容包含：

- **综合打分**：完成/总数、通过数、reward 和、通过率、token 数、耗时、底层模型
- **按版本维度**：2.1 / 3.0 分别统计
- **按难度维度**：易 / 中 / 难 分别统计
- **详细结果**：每个 case 的状态、reward、耗时、请求数、估算 token、日志链接
- **Case 运行中间结果**：每个 case 的 session.log / agent_output.log / verifier.log 最近 30 行

> 注意：当前 token 数为基于日志字符数的估算值。如需精确值，请在 psi-agent AI server 中记录每次请求的 `usage` 字段。

***

## 配置说明

编辑 `config/benchmark.yaml` 可调整：

- `model`：底层模型名称（会写入报告）
- `timeout.agent`：每个 case 最长运行时间
- `timeout.verifier_build`：verifier 镜像构建时间
- `cases`：case 列表

编辑 `.env` 可调整服务器地址、API key 等。

***

## 安全注意

- **不要把 `.env` 提交到仓库**。仓库已提供 `.env.example` 作为模板。
- 服务器密码/SSH key 仅保存在 `.env` 中，本地触发脚本读取后不会回显。
