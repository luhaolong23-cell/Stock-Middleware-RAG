# Stock Middleware RAG

一个面向财报场景的 RAG 中间层项目：负责把 PDF 财报解析、切块、入库、检索、问答，并产出可供下游消费的结构化结果。

它的定位不是“通用聊天机器人”，而是一个更偏工程化的数据与问答中间层，适合接在投研、筛选、量化、审计类流程前面。

## What It Does

- 解析财报 PDF
- 生成统一的 `text / table / image` chunk
- 写入数据库并建立检索索引
- 支持本地脚本问答或 FastAPI 问答
- 输出结构化 artifacts：
  - `extract_facts`
  - `analyze_fundamentals`
- 附带评测、审计、失败回放与数据导出脚本

## Architecture

```text
PDF report
-> parser
-> metadata extractor
-> chunker
-> embedding + storage
-> hybrid retrieval
-> rerank
-> answer guard + llm
-> API / local scripts / structured artifacts
```

## Tech Stack

- FastAPI
- SQLAlchemy
- PostgreSQL + pgvector
- SQLite fallback for local/simple cases
- OpenAI-compatible embedding / LLM endpoints

如果没有配置远程 embedding 或 LLM：

- embedding 会回退到 hash embedder
- 回答会回退到证据摘要模式

## Repository Layout

```text
app/        core application code
scripts/    CLI workflows and maintenance tools
docs/       operation and workflow documents
tests/      smoke tests and evaluation datasets
data/       small runtime support files only
```

当前仓库只保留了运行必需的小型支持文件，例如 `data/industry_map.json`；不会包含本地数据库、下载下来的 PDF、导出结果或密钥。

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure Database

在 `.env` 里至少配置：

```bash
DATABASE_URL=postgresql+psycopg://your_user:your_password@127.0.0.1:5432/stock_rag
```

初始化 PostgreSQL：

```bash
python scripts/init_postgres.py
```

### 3. Optional Remote Models

Embedding:

```bash
EMBEDDING_BASE_URL=https://your-embedding-endpoint/v1
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_MODEL=your_embedding_model
```

LLM:

```bash
LLM_BASE_URL=https://your-llm-endpoint/v1
LLM_API_KEY=your_api_key
LLM_MODEL=your_model_name
```

### 4. Start API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

API docs:

- `http://127.0.0.1:8000/api-docs`

## Main Workflows

### A. Script-Only Workflow

不启动后端，只用脚本完成下载、入库、问答、导出：

```bash
python scripts/download_latest_quarterly.py 600519 --no-ingest
python scripts/ingest_docs.py /absolute/path/to/report.pdf
python scripts/ask_document.py "贵州茅台2026年Q1营业收入是多少？" --top-k 3
python scripts/export_document_artifacts.py 600519
```

详细说明见：

- [docs/SCRIPT_WORKFLOW.md](docs/SCRIPT_WORKFLOW.md)

### B. API Workflow

启动后端后，可以通过 HTTP 调用：

- `POST /docs/ingest`
- `GET /docs`
- `POST /chat`
- `GET /docs/{document_id}/artifacts`

详细说明见：

- [docs/MANUAL_WORKFLOW.md](docs/MANUAL_WORKFLOW.md)

## Structured Outputs

当前有两类核心结构化输出：

### `extract_facts`

用于下游程序直接消费的结构化事实，例如：

- `revenue`
- `net_profit_attributable`
- `total_assets`
- `total_liabilities`
- `equity_attributable`
- `operating_cash_flow`
- `eps_basic`

### `analyze_fundamentals`

用于规则化分析和展示，例如：

- `snapshot`
- `ratios`
- `signals`
- `usable_for_calc`
- `summary`

字段协议见：

- [docs/NODE_SCHEMA.md](docs/NODE_SCHEMA.md)

## Evaluation

统一评测入口：

```bash
python scripts/eval.py --list
```

常用预设：

```bash
python scripts/eval.py smoke
python scripts/eval.py retrieval
python scripts/eval.py answer
python scripts/eval.py answer-full
python scripts/eval.py facts-smoke
python scripts/eval.py facts-full
```

最小回归通常先看：

```bash
python scripts/preflight.py
python scripts/eval.py smoke
```

## Operational Docs

- [docs/RUNBOOK.md](docs/RUNBOOK.md): deployment / regression / audit runbook
- [docs/MANUAL_WORKFLOW.md](docs/MANUAL_WORKFLOW.md): backend + manual API workflow
- [docs/SCRIPT_WORKFLOW.md](docs/SCRIPT_WORKFLOW.md): non-API script workflow
- [docs/NODE_SCHEMA.md](docs/NODE_SCHEMA.md): structured artifact schema

## Notes

- 这个项目更适合“财报事实问答、结构化抽取、基本面摘要”，不适合开放式投资建议。
- 如果修改了 embedding endpoint / model / dimensions，需要执行：

```bash
python scripts/rebuild_index.py
```

- 当前仓库是清理后的公开版本，不包含本地数据和私有密钥。

## 当前表格和图片策略

- 表格：优先尝试从 PDF 中提取，并转成可检索文本
- 图片：当前只做弱处理，保留 `figure_title / page_number / caption-like text`
- 多模态理解：暂不做，后续可以单独接入视觉模型
