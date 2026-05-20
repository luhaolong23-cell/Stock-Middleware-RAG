# Stock RAG Research Assistant

一个面向投研知识助手的 Python 单体架构骨架，先把离线入库、在线检索问答和评估脚手架定下来，后续可以逐步替换成真实的 Embedding、Reranker、LLM 和 PostgreSQL/pgvector。

## 架构

```text
research docs
-> ingestion pipeline
-> document/chunk storage
-> hybrid retrieval
-> rerank
-> answer guard + llm
-> FastAPI
```

当前实现刻意保持简洁：

- `FastAPI` 作为在线 API
- `SQLAlchemy + SQLite` 作为默认存储，支持切换到 `PostgreSQL + pgvector`
- 默认走远程 embedding 或 hash fallback，`KeywordRetriever` / `SimpleReranker` 作为轻量实现
- 文档入库、混合检索、引用返回、问答日志链路已打通
- 财报元素按 `text / table / image` 三类进入统一 chunk 流程

后续替换方向：

- SQLite -> PostgreSQL + pgvector
- 本地 `bge-m3` -> 其他 embedding 服务或 PostgreSQL/pgvector 检索
- `SimpleReranker` -> `bge-reranker`
- `LLMClient` 占位实现 -> OpenAI / Qwen / DeepSeek

## 目录

```text
app/
  api/
  core/
  ingestion/
  llm/
  models/
  retrieval/
  services/
  main.py
scripts/
tests/
data/
requirements.txt
```

## 快速启动

```bash
cd /home/luuuu/miniconda3/envs/stock-RAG
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

默认 `requirements.txt` 是当前主链依赖。项目默认不会主动连接远程 embedding / LLM；只有显式配置 `EMBEDDING_*` 或 `LLM_*` 环境变量时才会调用外部接口。
如果项目根目录存在 `.env`，当前配置模块会自动加载它；显式 `export` 的环境变量仍然优先。

如果你要按当前稳定基线部署、回归、导出审计快照，直接看 [docs/RUNBOOK.md](/home/luuuu/miniconda3/envs/stock-RAG/docs/RUNBOOK.md:1)。

### PostgreSQL + pgvector

如果要切到 PostgreSQL：

```bash
export DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/stock_rag
python scripts/init_postgres.py
```

当前实现会在 PostgreSQL 下自动：

- 创建 `vector` extension
- 创建 `documents / chunks` 表
- 创建 `GIN(search_vector)` 索引
- 创建 `HNSW(embedding)` 索引

如果你已经有历史 SQLite 数据，可以直接迁过去：

```bash
python scripts/migrate_sqlite_to_postgres.py --dest-url "$DATABASE_URL"
```

需要先清空目标库再迁移：

```bash
python scripts/migrate_sqlite_to_postgres.py --dest-url "$DATABASE_URL" --truncate
```

### 最新季度财报工作流

如果这个项目只分析最新季度财报，推荐直接用项目内脚本：

```bash
python scripts/download_latest_quarterly.py 600519
```

它会做两件事：

- 调用 `stock-data-downloader --mode latest-quarterly` 只下载最新一份季报
- 下载完成后，直接把这份 PDF 入库

只下载不入库：

```bash
python scripts/download_latest_quarterly.py 600519 --no-ingest
```

如果要扩文档规模，可以直接批量下载：

```bash
python scripts/download_latest_quarterly_batch.py 600519 600036 601318
```

或从股票列表文件批量下载：

```bash
python scripts/download_latest_quarterly_batch.py --stock-file data/watchlist.txt
```

如果确认下载后要直接入库，再显式加 `--ingest`：

```bash
python scripts/download_latest_quarterly_batch.py --stock-file data/watchlist.txt --ingest
```

### 远程 embedding

如果 embedding 和 LLM 分开部署，可以单独配置 embedding 接口：

```bash
export EMBEDDING_BASE_URL=https://your-embedding-endpoint/v1
export EMBEDDING_API_KEY=your_embedding_api_key
export EMBEDDING_MODEL=your_embedding_model
export EMBEDDING_TIMEOUT_SECONDS=60
```

当前逻辑是：

- 如果配置了 `EMBEDDING_BASE_URL + EMBEDDING_MODEL`，优先走远程 embedding
- 如果远程失败，自动回退到 hash embedder
- 如果没有配置远程 embedding，默认直接使用 hash embedder

可选：

```bash
export EMBEDDING_DIMENSIONS=1024
```

### LLM 接入

当前回答层支持 OpenAI 兼容接口。配置方式：

```bash
export LLM_BASE_URL=https://your-llm-endpoint/v1
export LLM_API_KEY=your_api_key
export LLM_MODEL=your_model_name
```

可选项：

```bash
export LLM_TIMEOUT_SECONDS=60
export LLM_MAX_TOKENS=800
export LLM_TEMPERATURE=0.1
export MIN_ANSWER_SCORE=0.015
```

如果没有配置 `LLM_*`，系统会回退成“证据摘要”模式，不会真正调用大模型。

## 常用接口

- `POST /docs/ingest`
- `GET /docs`
- `POST /chat`
- `GET /health`
- `GET /api-docs`

## 评测

现在只保留一个统一入口：

```bash
python scripts/eval.py --list
```

常用预设：

```bash
python scripts/eval.py sample
python scripts/eval.py sample --layer parse
python scripts/eval.py retrieval
python scripts/eval.py answer
python scripts/eval.py answer-full
python scripts/eval.py smoke
```

如果你有自定义数据集：

```bash
python scripts/eval.py --dataset tests/layered_eval.sample.json --layer all
```

当前内置预设对应关系：

```text
sample       -> tests/layered_eval.sample.json
smoke        -> tests/answer_eval_smoke.json
answer       -> tests/answer_eval_2026q1_22docs.json
answer-full  -> tests/answer_eval_full_2026q1_22docs.json
retrieval    -> tests/retrieval_eval_2026q1_22docs.json
```

推荐做法：

- `parse` 层只看元素解析是否符合预期
- `chunk` 层只看 chunk 数量、长度、关键字段是否被保留
- `retrieval` 层只看 top-k 是否命中正确证据块
- `answer` 层再看最终回答和引用

补充：

- `scripts/eval_rag.py` 现在只是兼容旧命令的壳子，后续统一用 `scripts/eval.py`
- `tests/test_answer_smoke.py` 是最小回归门禁，但当前环境里如果没有 `pytest`，直接跑 `python scripts/eval.py smoke` 就够了

### 当前切分方案

当前项目已经统一收敛到一套财报切分链路：

- `DocumentParser` 负责 PDF 解析
- `FinancialReportChunkerV2` 负责正文合并和大表拆分

脚本方式：

```bash
python scripts/ingest_docs.py /absolute/path/to/report.pdf
```

API 方式：

```json
{
  "file_path": "/absolute/path/to/report.pdf"
}
```

当前 chunker 的设计目标是：

1. 先用当前 `DocumentParser` 解析出元素
2. 按 `section -> paragraph block` 合并正文
3. 表格单独 chunk
4. 大表拆成“概览 chunk + 表头重复的行组 chunk”
5. 短答案 chunk 自动带上标题和页码
6. 后续继续沿用现有 hybrid retrieval

### 入库示例

```json
{
  "file_path": "/absolute/path/to/report.md"
}
```

### 问答示例

```json
{
  "query": "宁德时代最近一期公告提到的主要风险是什么？",
  "top_k": 5
}
```

## 当前边界

- 先把代码边界和主流程写清楚，不做复杂微服务拆分
- 默认实现可运行，但不是最终效果版本
- 真实生产落地时，重点替换 `retrieval/` 和 `llm/` 模块即可

## 财报元素设计

当前入库链路会先拆分文档元素，再做 chunk：

- `text`: 正文段落，继续按标题和长度切分
- `table`: 表格内容，单独保留成表格 chunk
- `image`: 图片弱处理，先保留图注、标题或页码信息

`chunks` 额外保留这些字段：

- `chunk_type`
- `page_number`
- `section_title`
- `table_title`
- `figure_title`
- `tokenized_text`
- `search_vector`
- `embedding`

这能保证两件事：

- 表格不会被普通段落切分打散
- 图片即使暂时不做多模态理解，也能以图注和页码形式参与检索

## 当前表格和图片策略

- 表格：优先尝试从 PDF 中提取，并转成可检索文本
- 图片：当前只做弱处理，保留 `figure_title / page_number / caption-like text`
- 多模态理解：暂不做，后续可以单独接入视觉模型
