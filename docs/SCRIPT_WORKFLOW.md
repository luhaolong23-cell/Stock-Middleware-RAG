# Stock-RAG Script Workflow

这份文档说明如何在**不启动 FastAPI 后端**的情况下，只通过脚本完成：

1. 下载财报 PDF
2. 入库文档
3. 本地问答
4. 导出结构化输出

适用场景：

- 你不想启动 `uvicorn`
- 你只想用命令行完成整套流程
- 你要做本地批处理或快速验证

## 1. 前提条件

进入项目目录：

```bash
cd /home/luuuu/miniconda3/envs/stock-RAG
```

先做一次环境自检：

```bash
python scripts/preflight.py
```

注意：

- 不启动后端，不代表不需要数据库
- 当前项目仍然需要可用的 `DATABASE_URL`
- 如果你配置了远程 embedding 或 LLM，对应服务也必须能访问

## 2. 下载财报 PDF

### 2.1 检查下载工具

下载脚本依赖本机命令 `stock-data-downloader`。

```bash
command -v stock-data-downloader
stock-data-downloader --help
```

### 2.2 下载单只股票最新季度财报

只下载，不入库：

```bash
python scripts/download_latest_quarterly.py 600519 --no-ingest
```

默认下载目录：

```text
data/latest-quarterly/
```

成功后会打印类似：

```text
downloaded latest quarterly report: /home/luuuu/miniconda3/envs/stock-RAG/data/latest-quarterly/600519_贵州茅台/600519_贵州茅台_2026_Q1报.pdf
```

如果你想自定义输出目录：

```bash
python scripts/download_latest_quarterly.py 600519 --no-ingest --output /tmp/stock-reports
```

### 2.3 批量下载

```bash
python scripts/download_latest_quarterly_batch.py 600519 600036 601318
```

或从文件读取股票列表：

```bash
python scripts/download_latest_quarterly_batch.py --stock-file data/watchlist.txt
```

默认批量下载目录：

```text
data/latest-quarterly-batch/
```

## 3. 入库文档

下载完成后，用入库脚本把 PDF 写入数据库。

示例：

```bash
python scripts/ingest_docs.py /home/luuuu/miniconda3/envs/stock-RAG/data/latest-quarterly/600519_贵州茅台/600519_贵州茅台_2026_Q1报.pdf
```

成功后会打印类似：

```text
ingested 600519_贵州茅台_2026_Q1报 -> 59 chunks (replaced 0, strategy=v2)
```

也可以一次入库多份 PDF：

```bash
python scripts/ingest_docs.py /path/to/a.pdf /path/to/b.pdf /path/to/c.pdf
```

## 4. 本地问答

项目中新增了一个本地问答脚本，不需要启动后端：

```bash
python scripts/ask_document.py "贵州茅台2026年Q1营业收入是多少？"
```

指定 `top_k`：

```bash
python scripts/ask_document.py "贵州茅台2026年Q1总资产是多少？" --top-k 3
```

如果你想看完整 JSON：

```bash
python scripts/ask_document.py "贵州茅台2026年Q1营业收入是多少？" --stdout-json
```

如果你不想写入 query log：

```bash
python scripts/ask_document.py "贵州茅台2026年Q1营业收入是多少？" --no-log
```

建议提问格式：

- 公司名
- 时间范围
- 标准财报指标名

例如：

- `贵州茅台2026年Q1营业收入是多少？`
- `光大银行2026年Q1总资产是多少？`
- `恒力石化2026年一季报归母净利润是多少？`

尽量优先用这些标准字段名：

- `营业收入`
- `总资产`
- `归母净利润`
- `经营活动现金流量净额`

## 5. 导出结构化输出

当前结构化输出主要有两类：

- `extract_facts`
- `analyze_fundamentals`

导出命令，推荐直接传股票代码：

```bash
python scripts/export_document_artifacts.py 600519
```

默认会输出到：

```text
data/exports/document_<document_id>_artifacts.json
```

脚本会按 `ticker=600519` 查找该股票最新的一篇文档并导出。

如果你想直接打印到终端：

```bash
python scripts/export_document_artifacts.py 600519 --stdout
```

如果你想自定义输出位置：

```bash
python scripts/export_document_artifacts.py 600519 --output /tmp/600519_artifacts.json
```

如果你确实要按 `document_id` 导出，也支持：

```bash
python scripts/export_document_artifacts.py 72 --by document-id
```

## 6. 一套完整脚本流示例

下面这套流程完全不需要启动 `uvicorn`：

### 6.1 下载 PDF

```bash
cd /home/luuuu/miniconda3/envs/stock-RAG
python scripts/download_latest_quarterly.py 600519 --no-ingest
```

### 6.2 入库 PDF

```bash
python scripts/ingest_docs.py /home/luuuu/miniconda3/envs/stock-RAG/data/latest-quarterly/600519_贵州茅台/600519_贵州茅台_2026_Q1报.pdf
```

### 6.3 本地问答

```bash
python scripts/ask_document.py "贵州茅台2026年Q1营业收入是多少？" --top-k 3
```

### 6.4 导出结构化输出

```bash
python scripts/export_document_artifacts.py 600519
```

### 6.5 最小回归

```bash
python scripts/eval.py smoke
```

通过标准：

- `passed: 8`
- `pass_rate: 1.0`

## 7. 一步下载并入库

如果你不想把“下载”和“入库”拆成两步，也可以直接：

```bash
python scripts/download_latest_quarterly.py 600519
```

这个命令会：

1. 下载最新季度财报
2. 直接把 PDF 入库

批量版本：

```bash
python scripts/download_latest_quarterly_batch.py 600519 600036 601318 --ingest
```

## 8. 常见问题

### 8.1 不启动后端，为什么还能入库和问答

因为这些脚本都是直接调用本地 Python 代码和数据库，不经过 HTTP API。

例如：

- `scripts/ingest_docs.py` 直接调用 `IngestionPipeline`
- `scripts/ask_document.py` 直接调用 `ChatService`
- `scripts/export_document_artifacts.py` 直接查数据库导出 JSON

### 8.2 哪些事情一定要启动后端

只有你要使用这些 HTTP 接口时才必须启动后端：

- `/docs/ingest`
- `/docs`
- `/chat`
- `/docs/{document_id}/artifacts`

### 8.3 脚本问答返回“证据不足”

优先检查：

1. 文档是否已经成功入库
2. 数据库是否可用
3. embedding 是否可用
4. 提问是否使用了标准财报指标名

### 8.4 脚本问答偶尔退化成证据摘要

如果 LLM 接口限流或短时失败，系统会自动回退到证据摘要模式。
这通常不代表数据库或检索链路坏了。
