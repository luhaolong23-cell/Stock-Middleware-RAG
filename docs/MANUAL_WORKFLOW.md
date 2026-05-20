# Stock-RAG Manual Workflow

这份文档说明如何手动完成以下流程：

1. 启动后端
2. 手动下载财报 PDF
3. 入库文档
4. 发起问答
5. 导出结构化输出

## 1. 启动后端

进入项目目录：

```bash
cd /home/luuuu/miniconda3/envs/stock-RAG
```

建议先做一次环境自检：

```bash
python scripts/preflight.py
```

启动 FastAPI：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

新开一个终端检查健康状态：

```bash
curl http://127.0.0.1:8000/health
```

期望返回：

```json
{"status":"ok","app":"Stock RAG Research Assistant","env":"dev"}
```

接口文档：

- `http://127.0.0.1:8000/api-docs`

## 2. 手动下载文档

### 2.1 先确认下载工具可用

项目里的下载脚本依赖本机命令 `stock-data-downloader`。

检查方式：

```bash
command -v stock-data-downloader
stock-data-downloader --help
```

如果这两个命令不能正常执行，先安装或修复下载工具，再继续后面的步骤。

### 2.2 下载单只股票最新季度财报

只下载，不入库：

```bash
python scripts/download_latest_quarterly.py 600519 --no-ingest
```

默认下载目录：

```text
data/latest-quarterly/
```

下载成功后，脚本会打印类似：

```text
downloaded latest quarterly report: /home/luuuu/miniconda3/envs/stock-RAG/data/latest-quarterly/600519_贵州茅台/600519_贵州茅台_2026_Q1报.pdf
```

也可以指定输出目录：

```bash
python scripts/download_latest_quarterly.py 600519 --no-ingest --output /tmp/stock-reports
```

### 2.3 批量下载最新季度财报

只下载，不入库：

```bash
python scripts/download_latest_quarterly_batch.py 600519 600036 601318
```

或者从文件读取股票列表：

```bash
python scripts/download_latest_quarterly_batch.py --stock-file data/watchlist.txt
```

默认批量下载目录：

```text
data/latest-quarterly-batch/
```

## 3. 入库文档

这个项目的文档入库有两种方式：

- 用脚本直接入库
- 用 API 传本机文件路径入库

### 3.1 用脚本入库

假设你刚下载到了这份 PDF：

```text
/home/luuuu/miniconda3/envs/stock-RAG/data/latest-quarterly/600519_贵州茅台/600519_贵州茅台_2026_Q1报.pdf
```

入库命令：

```bash
python scripts/ingest_docs.py /home/luuuu/miniconda3/envs/stock-RAG/data/latest-quarterly/600519_贵州茅台/600519_贵州茅台_2026_Q1报.pdf
```

成功后会打印类似：

```text
ingested 600519_贵州茅台_2026_Q1报 -> 59 chunks (replaced 0, strategy=v2)
```

### 3.2 用 API 入库

`/docs/ingest` 不是上传文件，而是传本机绝对路径。

```bash
curl -X POST http://127.0.0.1:8000/docs/ingest \
  -H 'Content-Type: application/json' \
  -d '{"file_path":"/home/luuuu/miniconda3/envs/stock-RAG/data/latest-quarterly/600519_贵州茅台/600519_贵州茅台_2026_Q1报.pdf","overwrite":true}'
```

期望返回类似：

```json
{
  "document_id": 72,
  "title": "600519_贵州茅台_2026_Q1报",
  "chunk_count": 59,
  "replaced_count": 0,
  "strategy": "v2"
}
```

### 3.3 查看已入库文档

```bash
curl http://127.0.0.1:8000/docs
```

如果你只想看简单列表，可以重点关注这些字段：

- `id`
- `title`
- `source`
- `chunk_count`
- `artifact_types`

## 4. 发起问答

### 4.1 通过 API 问答

示例 1：问营业收入

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"贵州茅台2026年Q1营业收入是多少？","top_k":3}'
```

示例 2：问总资产

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"贵州茅台2026年Q1总资产是多少？","top_k":3}'
```

建议提问格式：

- 公司名
- 时间范围
- 标准财报指标名

例如：

- `贵州茅台2026年Q1营业收入是多少？`
- `光大银行2026年Q1总资产是多少？`
- `恒力石化2026年一季报归母净利润是多少？`

尽量优先使用标准字段名：

- `营业收入`
- `总资产`
- `归母净利润`
- `经营活动现金流量净额`

### 4.2 期望结果

返回 JSON 里重点看：

- `answer`
- `citations`

`citations` 里应该能看到：

- 命中的文档标题
- 页码
- 片段摘要
- 检索分数

## 5. 导出结构化输出

当前项目的结构化输出主要有两类：

- `extract_facts`
- `analyze_fundamentals`

### 5.1 先拿到 document_id

先查文档列表：

```bash
curl http://127.0.0.1:8000/docs
```

假设目标文档的 `id` 是 `72`。

### 5.2 通过 API 查看结构化输出

```bash
curl http://127.0.0.1:8000/docs/72/artifacts
```

返回结果里每一项会包含：

- `artifact_type`
- `version`
- `status`
- `payload`

其中 `payload` 就是结构化输出正文。

### 5.3 导出为本地 JSON 文件

项目内已经提供导出脚本：

```bash
python scripts/export_document_artifacts.py 600519
```

默认输出到：

```text
data/exports/document_<document_id>_artifacts.json
```

脚本会按 `ticker=600519` 查找该股票最新的一篇文档并导出。

直接打印到终端：

```bash
python scripts/export_document_artifacts.py 600519 --stdout
```

自定义输出文件：

```bash
python scripts/export_document_artifacts.py 600519 --output /tmp/600519_artifacts.json
```

如果你确实要按 `document_id` 导出，也支持：

```bash
python scripts/export_document_artifacts.py 72 --by document-id
```

### 5.4 结构化输出内容说明

`extract_facts` 里通常会有：

- `basic_info`
- `facts`
- `metrics`
- `data_quality`

`analyze_fundamentals` 里通常会有：

- `snapshot`
- `ratios`
- `signals`
- `usable_for_calc`
- `summary`

字段协议见：

- [NODE_SCHEMA.md](/home/luuuu/miniconda3/envs/stock-RAG/docs/NODE_SCHEMA.md:1)

## 6. 一套完整手动流程示例

### 6.1 启动后端

```bash
cd /home/luuuu/miniconda3/envs/stock-RAG
python scripts/preflight.py
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 6.2 下载 PDF

```bash
python scripts/download_latest_quarterly.py 600519 --no-ingest
```

### 6.3 入库 PDF

```bash
python scripts/ingest_docs.py /home/luuuu/miniconda3/envs/stock-RAG/data/latest-quarterly/600519_贵州茅台/600519_贵州茅台_2026_Q1报.pdf
```

### 6.4 查看文档

```bash
curl http://127.0.0.1:8000/docs
```

### 6.5 发起问答

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"贵州茅台2026年Q1营业收入是多少？","top_k":3}'
```

### 6.6 导出结构化输出

```bash
python scripts/export_document_artifacts.py 600519
```

### 6.7 最小回归验证

```bash
python scripts/eval.py smoke
```

通过标准：

- `passed: 8`
- `pass_rate: 1.0`

## 7. 常见问题

### 7.1 下载成功了但找不到 PDF

检查这两个目录：

- `data/latest-quarterly/`
- `data/latest-quarterly-batch/`

### 7.2 入库时报文件不存在

传给入库脚本或 `/docs/ingest` 的必须是本机真实存在的绝对路径。

### 7.3 问答返回“证据不足”

优先检查：

1. 文档是否真的已经入库
2. 提问里是否带了公司名和时间
3. 指标名是否使用了标准财报词

### 7.4 问答偶尔变成证据摘要

当前配置的 LLM 可能会遇到限流或短时失败。
代码会自动回退到证据摘要模式，这不一定代表系统不可用。
