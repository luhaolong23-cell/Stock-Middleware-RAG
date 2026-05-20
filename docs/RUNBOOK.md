# Stock-RAG Runbook

这份 runbook 只覆盖当前稳定落地方式：`PostgreSQL + pgvector`、本地 `FastAPI` 服务、财报 PDF 入库、统一评测和 artifact 审计。

## 1. 运行边界

- 主数据库：`PostgreSQL`
- 主流程：`下载/准备 PDF -> ingest -> generate artifacts -> eval -> audit -> serve`
- 结构化输出：
  - `extract_facts`
  - `analyze_fundamentals`
- 当前稳定基线：
  - `answer smoke = 8/8`
  - `facts smoke = 2/2`
  - `facts full = 4/4`
  - `artifact audit baseline = data/audits/artifact_audit_20260515-baseline.*`

## 2. 首次部署

### 2.1 安装依赖

```bash
cd /home/luuuu/miniconda3/envs/stock-RAG
pip install -r requirements.txt
```

### 2.2 配置环境变量

复制示例文件并按实际环境填写：

```bash
cp .env.example .env
```

当前项目会自动加载根目录 `.env`；如果同时存在 shell `export` 和 `.env`，以 shell 环境变量为准。

至少需要确认这些项：

- `DATABASE_URL`
- `EMBEDDING_BASE_URL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_MODEL`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`

如果不配置 `EMBEDDING_*` / `LLM_*`，系统会退化成：

- embedding 走 hash fallback
- 回答走证据摘要模式

### 2.3 初始化 PostgreSQL

```bash
export DATABASE_URL='postgresql+psycopg://your_user:your_password@127.0.0.1:5432/stock_rag'
python scripts/init_postgres.py
```

## 3. 文档入库

### 3.1 单文件入库

```bash
export DATABASE_URL='postgresql+psycopg://your_user:your_password@127.0.0.1:5432/stock_rag'
python scripts/ingest_docs.py /absolute/path/to/report.pdf
```

### 3.2 下载最新季度财报并入库

```bash
python scripts/download_latest_quarterly.py 600519
```

批量下载后再入库：

```bash
python scripts/download_latest_quarterly_batch.py --stock-file data/watchlist.txt --ingest
```

### 3.3 更换 embedding 模型后的处理

如果变更以下任一项，必须重建索引：

- `EMBEDDING_BASE_URL`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIMENSIONS`

重建命令：

```bash
export DATABASE_URL='postgresql+psycopg://your_user:your_password@127.0.0.1:5432/stock_rag'
python scripts/rebuild_index.py
```

## 4. 服务启动

```bash
export DATABASE_URL='postgresql+psycopg://your_user:your_password@127.0.0.1:5432/stock_rag'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后可检查：

```bash
curl http://127.0.0.1:8000/health
```

接口文档入口：`http://127.0.0.1:8000/api-docs`

## 5. 日常验证

### 5.0 环境自检

```bash
python scripts/preflight.py
python scripts/preflight.py --with-eval
```

建议：

- 服务启动前至少跑一次 `python scripts/preflight.py`
- 发版前跑一次 `python scripts/preflight.py --with-eval`

### 5.1 最小回归

```bash
export DATABASE_URL='postgresql+psycopg://your_user:your_password@127.0.0.1:5432/stock_rag'
python scripts/eval.py facts-smoke
python scripts/eval.py smoke
```

### 5.2 发版前回归

```bash
export DATABASE_URL='postgresql+psycopg://your_user:your_password@127.0.0.1:5432/stock_rag'
python scripts/eval.py facts-full
python scripts/eval.py answer-full
python scripts/eval.py retrieval
```

### 5.3 artifact 审计快照

```bash
export DATABASE_URL='postgresql+psycopg://your_user:your_password@127.0.0.1:5432/stock_rag'
python scripts/export_artifact_audit.py --timestamp 20260515-baseline
```

重点关注：

- `missing_metrics`
- `low_confidence_metrics`
- `derived_metrics`
- `with_industry / without_industry`

## 6. 失败回放

查看最近日志：

```bash
python scripts/review_query_logs.py --list-recent 10
```

标记失败样本：

```bash
python scripts/review_query_logs.py \
  --query-log-id 384 \
  --label wrong_value \
  --expected-answer-contains 4,919,070.54 \
  --expected-citation-title 600346_恒力石化_2026_Q1报
```

重放失败：

```bash
python scripts/replay_failures.py --status open
```

## 7. 对外使用边界

- 适合：财报事实问答、结构化字段抽取、基本面摘要
- 不适合：开放式投资建议、自动下单、无约束估值推理
- 下游量化模块应优先消费：
  - `usable_for_calc.raw_metrics`
  - `usable_for_calc.derived_metrics`
- 应排除：
  - `usable_for_calc.excluded_metrics`
  - `low_confidence_metrics`

`extract_facts` / `analyze_fundamentals` 的正式字段协议见 [NODE_SCHEMA.md](/home/luuuu/miniconda3/envs/stock-RAG/docs/NODE_SCHEMA.md:1)。

## 8. 发布前检查

发布前至少确认以下 8 项：

1. `DATABASE_URL` 指向 PostgreSQL，而不是 SQLite。
2. `.env` 中没有硬编码真实密钥到代码仓库。
3. `facts-smoke` 和 `smoke` 全通过。
4. 改了 facts 规则时，`facts-full` 全通过。
5. 改了回答层时，`answer-full` 全通过。
6. 已导出一份新的 artifact audit 快照。
7. `missing_metrics` / `low_confidence_metrics` 没有明显恶化。
8. `/health` 正常返回。
