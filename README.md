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
# 测试主分支
python bin/trigger_benchmark.py --branch main --wait

# 测试指定分支
python bin/trigger_benchmark.py --branch feature-xxx --wait
```

### 4. 查看报告

报告自动下载到 `reports/` 目录，包含：

- 综合打分（完成数/总数、通过率、token 消耗、耗时）
- 按版本/难度维度统计
- 每个 Case 的详细结果（状态、reward、请求数、token、日志片段）

## 自定义 Case 列表

编辑 `case_metadata.json`，设置 `"enabled": false` 跳过不需要的 Case：

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