from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
PRESENTATION_DIR = ROOT / "presentation"
ASSETS_DIR = PRESENTATION_DIR / "assets"
DATA_DIR = PRESENTATION_DIR / "data"
SCREENSHOT_DIR = PRESENTATION_DIR / "screenshots"

FACTS_DATASET = ROOT / "tests" / "facts_eval_gold_manual_2026q1_26docs.json"
AUDIT_JSON = ROOT / "data" / "audits" / "artifact_audit_20260516-facts-26docs.json"

PRIMARY = "#0f766e"
SECONDARY = "#0ea5e9"
ACCENT = "#f97316"
INK = "#0f172a"
MUTED = "#475569"
BG = "#f8fafc"

plt.rcParams["font.family"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def run_json(command: list[str]) -> dict:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def build_accuracy_uplift_chart(before_acc: float, after_acc: float, exact_rate: float, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 6), dpi=180)
    labels = ["Field accuracy", "Exact docs"]
    before = [before_acc * 100, 0.0]
    after = [after_acc * 100, exact_rate * 100]
    ypos = range(len(labels))

    ax.barh([y + 0.18 for y in ypos], before, height=0.32, color="#cbd5e1", label="Before")
    ax.barh([y - 0.18 for y in ypos], after, height=0.32, color=PRIMARY, label="After")

    for idx, value in enumerate(before):
        ax.text(value + 1, idx + 0.18, f"{value:.2f}%", va="center", ha="left", color=MUTED, fontsize=11)
    for idx, value in enumerate(after):
        ax.text(value + 1, idx - 0.18, f"{value:.2f}%", va="center", ha="left", color=INK, fontsize=11, weight="bold")

    ax.set_xlim(0, 110)
    ax.set_yticks(list(ypos))
    ax.set_yticklabels(labels, fontsize=12)
    ax.set_xlabel("Accuracy / match rate (%)", fontsize=12)
    ax.set_title("Truth-set evaluation: before vs after", fontsize=16, weight="bold", pad=14)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.invert_yaxis()
    ax.legend(frameon=False, loc="lower right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def build_field_breakdown_chart(field_breakdown: dict, path: Path) -> None:
    ordered = sorted(field_breakdown.items(), key=lambda item: item[1]["accuracy"], reverse=True)
    labels = [name for name, _ in ordered]
    values = [details["accuracy"] * 100 for _, details in ordered]
    colors = [PRIMARY if value >= 95 else ACCENT for value in values]

    fig, ax = plt.subplots(figsize=(12, 6.8), dpi=180)
    bars = ax.bar(labels, values, color=colors, width=0.62)
    ax.set_ylim(0, 110)
    ax.set_ylabel("Accuracy (%)", fontsize=12)
    ax.set_title("Accuracy of 8 core fields", fontsize=16, weight="bold", pad=14)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="x", rotation=20, labelsize=10)
    ax.set_facecolor(BG)
    fig.patch.set_facecolor(BG)

    for bar, value in zip(bars, values, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 2, f"{value:.1f}%", ha="center", va="bottom", fontsize=10, color=INK)

    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def build_calc_coverage_chart(total_fields: int, usable_fields: int, low_conf: int, derived: int, missing: int, path: Path) -> None:
    usable_raw = usable_fields - derived
    excluded = total_fields - usable_fields - missing
    labels = ["Raw usable", "Excluded", "Derived usable", "Missing"]
    values = [usable_raw, max(excluded, 0), derived, missing]
    colors = [PRIMARY, ACCENT, SECONDARY, "#94a3b8"]

    fig, ax = plt.subplots(figsize=(9.2, 6.5), dpi=180)
    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels,
        colors=colors,
        autopct=lambda pct: f"{pct:.1f}%",
        startangle=110,
        wedgeprops={"linewidth": 1.5, "edgecolor": BG},
        textprops={"color": INK, "fontsize": 11},
    )
    for autotext in autotexts:
        autotext.set_color("white")
        autotext.set_weight("bold")
        autotext.set_fontsize(10)

    ax.set_title("Structured coverage across 26 reports", fontsize=16, weight="bold", pad=16)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def build_terminal_snippet(answer_eval: dict, facts_eval: dict) -> str:
    answer = answer_eval["answer"]
    lines = [
        "$ python scripts/eval.py answer-full",
        f'{{ "total": {answer["total"]}, "passed": {answer["passed"]}, "pass_rate": {answer["pass_rate"]:.4f} }}',
        "",
        "$ python scripts/eval_facts_gold.py --dataset tests/facts_eval_gold_manual_2026q1_26docs.json",
        "{",
        f'  "documents": {facts_eval["documents"]},',
        f'  "document_exact_matches": {facts_eval["document_exact_matches"]},',
        f'  "matched_fields": {facts_eval["matched_fields"]},',
        f'  "field_accuracy": {facts_eval["field_accuracy"]:.4f}',
        "}",
    ]
    return "\n".join(lines)


def build_artifact_snippet(audit_rows: list[dict]) -> str:
    sample = next(row for row in audit_rows if row["title"] == "600036_招商银行_2026_Q1报")
    slim = {
        "title": sample["title"],
        "industry": sample["industry"],
        "available_metric_count": sample["available_metric_count"],
        "usable_for_calc": {
            "raw_metrics": sample["usable_raw_metrics"],
            "derived_metrics": sample["usable_derived_metrics"],
            "excluded_metrics": sample["usable_excluded_metrics"],
        },
    }
    return json.dumps(slim, ensure_ascii=False, indent=2)


def escape_block(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def build_html(context: dict) -> str:
    highlights = "".join(
        f'<div class="metric-card"><div class="metric-label">{item["label"]}</div><div class="metric-value">{item["value"]}</div><div class="metric-note">{item["note"]}</div></div>'
        for item in context["metrics"]
    )
    bullets = "".join(f"<li>{html.escape(item)}</li>" for item in context["engineering_bullets"])
    issues = "".join(f"<li>{html.escape(item)}</li>" for item in context["issue_bullets"])
    hooks = "".join(f"<li>{html.escape(item)}</li>" for item in context["hook_bullets"])

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stock-RAG Showcase Deck</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --card: rgba(255,255,255,0.86);
      --line: rgba(15, 23, 42, 0.08);
      --ink: #0f172a;
      --muted: #475569;
      --primary: {PRIMARY};
      --secondary: {SECONDARY};
      --accent: {ACCENT};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Noto Sans SC", "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(14,165,233,0.12), transparent 28%),
        radial-gradient(circle at top right, rgba(15,118,110,0.14), transparent 32%),
        linear-gradient(180deg, #f8fafc 0%, #eef6ff 100%);
    }}
    .deck {{
      width: 1600px;
      min-height: 900px;
      margin: 0 auto;
    }}
    .slide {{
      width: 1600px;
      height: 900px;
      padding: 58px 68px;
      position: relative;
      overflow: hidden;
      page-break-after: always;
      display: none;
    }}
    .slide::before {{
      content: "";
      position: absolute;
      inset: 24px;
      border-radius: 28px;
      border: 1px solid rgba(255,255,255,0.55);
      background: linear-gradient(160deg, rgba(255,255,255,0.86), rgba(255,255,255,0.74));
      box-shadow: 0 24px 80px rgba(15, 23, 42, 0.08);
      z-index: 0;
    }}
    .slide > * {{ position: relative; z-index: 1; }}
    .slide.active {{ display: block; }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-size: 20px;
      color: var(--primary);
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .eyebrow::before {{
      content: "";
      width: 36px;
      height: 4px;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--primary), var(--secondary));
    }}
    h1 {{
      margin: 18px 0 12px;
      font-size: 64px;
      line-height: 1.05;
      letter-spacing: -0.03em;
    }}
    h2 {{
      margin: 16px 0 10px;
      font-size: 34px;
      line-height: 1.15;
      letter-spacing: -0.02em;
    }}
    p.lead {{
      margin: 0;
      max-width: 1080px;
      font-size: 24px;
      line-height: 1.65;
      color: var(--muted);
    }}
    .hero-grid {{
      display: grid;
      grid-template-columns: 1.2fr 0.9fr;
      gap: 28px;
      margin-top: 36px;
      align-items: stretch;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 24px;
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.05);
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .metric-card {{
      background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(248,250,252,0.9));
      border: 1px solid rgba(15, 23, 42, 0.06);
      border-radius: 20px;
      padding: 22px;
    }}
    .metric-label {{
      font-size: 18px;
      color: var(--muted);
    }}
    .metric-value {{
      margin-top: 10px;
      font-size: 44px;
      font-weight: 800;
      letter-spacing: -0.04em;
    }}
    .metric-note {{
      margin-top: 10px;
      font-size: 16px;
      color: var(--muted);
      line-height: 1.55;
    }}
    .tag-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 20px;
    }}
    .tag {{
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(14,165,233,0.08);
      border: 1px solid rgba(14,165,233,0.18);
      color: var(--ink);
      font-size: 17px;
      font-weight: 700;
    }}
    .columns {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 28px;
      margin-top: 24px;
    }}
    .triple {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 22px;
      margin-top: 24px;
    }}
    ul {{
      margin: 14px 0 0 20px;
      padding: 0;
      font-size: 22px;
      line-height: 1.75;
      color: var(--muted);
    }}
    .small-list {{
      font-size: 18px;
      line-height: 1.55;
    }}
    .stage-list {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin-top: 24px;
    }}
    .stage {{
      background: linear-gradient(180deg, rgba(255,255,255,0.9), rgba(240,249,255,0.9));
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 22px;
      min-height: 170px;
    }}
    .stage-title {{
      font-size: 24px;
      font-weight: 800;
      margin-bottom: 10px;
    }}
    .stage-text {{
      font-size: 18px;
      line-height: 1.65;
      color: var(--muted);
    }}
    .asset {{
      width: 100%;
      border-radius: 20px;
      border: 1px solid rgba(15,23,42,0.08);
      background: white;
    }}
    .code-block {{
      margin-top: 14px;
      background: #0f172a;
      color: #e2e8f0;
      border-radius: 20px;
      padding: 20px 22px;
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 14px;
      line-height: 1.6;
      min-height: 290px;
      overflow: hidden;
      white-space: normal;
    }}
    .asset.compact {{
      max-height: 200px;
      object-fit: contain;
    }}
    .code-title {{
      font-size: 18px;
      color: var(--muted);
      margin-bottom: 10px;
      font-weight: 700;
    }}
    .footer {{
      position: absolute;
      left: 70px;
      right: 70px;
      bottom: 54px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 18px;
      color: var(--muted);
    }}
    .footer strong {{
      color: var(--ink);
    }}
    .big-quote {{
      margin-top: 30px;
      font-size: 34px;
      line-height: 1.5;
      font-weight: 700;
      letter-spacing: -0.02em;
      max-width: 1220px;
    }}
    .accent {{
      color: var(--primary);
    }}
    .callout {{
      margin-top: 24px;
      padding: 18px 20px;
      border-radius: 18px;
      background: linear-gradient(90deg, rgba(15,118,110,0.08), rgba(14,165,233,0.08));
      border: 1px solid rgba(15,118,110,0.14);
      font-size: 22px;
      line-height: 1.6;
      color: var(--ink);
    }}
  </style>
</head>
<body>
  <div class="deck">
    <section class="slide" data-slide="1">
      <div class="eyebrow">Resume Showcase</div>
      <h1>Stock-RAG：把财报问答系统做成<br>可评测、可回归、可落地的数据中间层</h1>
      <p class="lead">项目面向 A 股季度财报，打通 <strong>PDF 入库、混合检索、证据问答、结构化抽取、基本面分析</strong> 全链路。重点不是“堆模型”，而是把系统做成一个能持续迭代的工程产品。</p>
      <div class="hero-grid">
        <div class="card">
          <h2>核心成果</h2>
          <div class="metric-grid">
            {highlights}
          </div>
          <div class="tag-row">
            <span class="tag">FastAPI + SQLAlchemy</span>
            <span class="tag">SQLite / PostgreSQL + pgvector</span>
            <span class="tag">Hybrid Retrieval + Rerank</span>
            <span class="tag">Artifact Audit + Truth Eval</span>
          </div>
        </div>
        <div class="card">
          <h2>为什么这个项目有工程含量</h2>
          <ul>
            <li>不是只做问答 Demo，而是提供 <strong>extract_facts + analyze_fundamentals</strong> 两类可复用产物。</li>
            <li>把“能回答”拆成可测层次：<strong>parse / chunk / retrieval / answer / facts</strong>。</li>
            <li>给结构化数据增加 <strong>来源语义、置信边界、可计算边界</strong>，方便下游量化模块直接消费。</li>
            <li>引入 <strong>人工真值集</strong>，用字段级准确率而不是主观感觉来驱动优化。</li>
          </ul>
        </div>
      </div>
      <div class="footer"><span>Slide 1 / 6</span><strong>项目概览与结果总览</strong></div>
    </section>

    <section class="slide" data-slide="2">
      <div class="eyebrow">System Design</div>
      <h2>系统不是单点功能，而是一条完整可运营的财报分析链路</h2>
      <div class="stage-list">
        <div class="stage">
          <div class="stage-title">1. 文档进入系统</div>
          <div class="stage-text">下载最新季报、解析 PDF、切分正文和表格、生成 chunk 并入库。</div>
        </div>
        <div class="stage">
          <div class="stage-title">2. 混合检索问答</div>
          <div class="stage-text">词法检索 + 向量检索 + rerank，返回带引用的证据回答，并支持无 LLM 模式的安全降级。</div>
        </div>
        <div class="stage">
          <div class="stage-title">3. 结构化中间层</div>
          <div class="stage-text">入库后自动产出 <strong>extract_facts</strong> 和 <strong>analyze_fundamentals</strong>，供估值和量化模块复用。</div>
        </div>
      </div>
      <div class="columns">
        <div class="card">
          <h2>工程主链</h2>
          <ul>
            <li><strong>parse → chunk → embed → store</strong> 是基础入库主链。</li>
            <li>我把主链扩成 <strong>parse → chunk → embed → store → extract_facts → analyze_fundamentals</strong>。</li>
            <li>输出的不只是 JSON，而是带 <strong>provenance</strong> 和 <strong>usable_for_calc</strong> 语义的结构化数据。</li>
          </ul>
          <div class="callout">项目定位从“财报问答 RAG Demo”升级成“可接工作流的基本面数据中间层”。</div>
        </div>
        <div class="card">
          <h2>对下游的价值</h2>
          <ul>
            <li>问答场景：回答“营业收入是多少”“总资产是多少”。</li>
            <li>分析场景：直接生成 <strong>净利率 / 资产负债率 / 经营现金流率</strong>。</li>
            <li>量化场景：下游只消费 <strong>usable_for_calc.raw_metrics</strong> 和 <strong>usable_for_calc.derived_metrics</strong>。</li>
            <li>运维场景：Runbook、Preflight、审计快照让系统具备试运行条件。</li>
          </ul>
        </div>
      </div>
      <div class="footer"><span>Slide 2 / 6</span><strong>架构与产品化设计</strong></div>
    </section>

    <section class="slide" data-slide="3">
      <div class="eyebrow">Engineering Thinking</div>
      <h2>这轮优化的重点是把系统做成“能持续迭代”的工程，而不是一次性结果</h2>
      <div class="triple">
        <div class="card">
          <h2>评测收口</h2>
          <ul class="small-list">
            {bullets}
          </ul>
        </div>
        <div class="card">
          <h2>数据治理</h2>
          <ul class="small-list">
            <li>每个 fact 标记 <strong>raw_extracted / derived / downgraded_raw</strong>。</li>
            <li>分析节点明确区分 <strong>raw_metrics / derived_metrics / excluded_metrics</strong>。</li>
            <li>审计快照导出 <strong>missing / low_confidence / derived</strong> 统计，方便做质量回归。</li>
            <li>单位、表格上下文、页码优先级和一致性校验都进入规则层，而不是散落在脚本里。</li>
          </ul>
        </div>
        <div class="card">
          <h2>部署与运维</h2>
          <ul class="small-list">
            <li>增加 <strong>.env.example</strong>，去掉硬编码远程模型配置。</li>
            <li>补齐 <strong>docs/RUNBOOK.md</strong> 和 <strong>scripts/preflight.py</strong>。</li>
            <li>修复 Swagger 文档占用 <strong>/docs</strong> 路由的问题，业务接口和 API 文档边界更清晰。</li>
            <li>支持无远程 embedding / LLM 时的安全退化，不会因为配置缺失直接打挂。</li>
          </ul>
        </div>
      </div>
      <div class="big-quote">这类工作体现的是 <span class="accent">工程化思维</span>：先建立清晰边界和可验证机制，再优化模型效果，而不是只看单次跑通。</div>
      <div class="footer"><span>Slide 3 / 6</span><strong>工程亮点</strong></div>
    </section>

    <section class="slide" data-slide="4">
      <div class="eyebrow">Measured Impact</div>
      <h2>用人工真值集驱动抽取器优化，把“看起来对”变成“字段级可验证”</h2>
      <div class="columns">
        <div class="card">
          <img class="asset" src="assets/accuracy_uplift.png" alt="accuracy uplift chart">
          <div class="callout">字段级准确率从 <strong>77.88%</strong> 提升到 <strong>95.67%</strong>，文档级完全命中从 <strong>0/26</strong> 提升到 <strong>18/26</strong>。</div>
        </div>
        <div class="card">
          <img class="asset" src="assets/field_breakdown.png" alt="field breakdown chart">
          <div class="tag-row">
            <span class="tag">revenue 100%</span>
            <span class="tag">total_liabilities 100%</span>
            <span class="tag">total_assets 96.15%</span>
            <span class="tag">net_profit 92.31%</span>
          </div>
        </div>
      </div>
      <div class="footer"><span>Slide 4 / 6</span><strong>真实优化幅度与方法</strong></div>
    </section>

    <section class="slide" data-slide="5">
      <div class="eyebrow">Live Evidence</div>
      <h2>项目实况可以直接展示：评测结果、审计输出、可计算字段边界都能落到文件</h2>
      <div class="columns">
        <div class="card">
          <div class="code-title">评测命令与最新结果</div>
          <div class="code-block">{escape_block(context["terminal_snippet"])}</div>
        </div>
        <div class="card">
          <div class="code-title">实际 artifact audit 摘要样例</div>
          <div class="code-block">{escape_block(context["artifact_snippet"])}</div>
        </div>
      </div>
      <div class="footer"><span>Slide 5 / 6</span><strong>项目实况展示</strong></div>
    </section>

    <section class="slide" data-slide="6">
      <div class="eyebrow">Interview Hook</div>
      <h2>面试时可以这样讲这个项目</h2>
      <div class="card">
        <div class="big-quote">我做的不是一个只会“回答财报问题”的 RAG 原型，而是把它推进成了一个有 <span class="accent">结构化中间层、统一评测体系、人工真值校验、审计和回放机制</span> 的财报数据系统。最有代表性的一轮优化，是我先补人工真值集，再针对单位、脚注、主表冲突、银行报表格式做抽取器修复，把 26 份财报 208 个字段的真实准确率从 77.88% 提升到了 95.67%。</div>
      </div>
      <div class="columns">
        <div class="card">
          <h2>适合强调的特点</h2>
          <ul class="small-list">
            {hooks}
          </ul>
        </div>
        <div class="card">
          <h2>你可以带走的展示文件</h2>
          <ul class="small-list">
            <li><strong>index.html</strong>：可直接全屏演示。</li>
            <li><strong>stock-rag-showcase.pdf</strong>：适合发给老师、面试官或投屏展示。</li>
            <li><strong>screenshots/slide-*.png</strong>：可直接插进简历附件、答辩材料、公众号推文。</li>
            <li><strong>data/*.json</strong>：保留本次评测与审计结果，保证数字可回溯。</li>
          </ul>
        </div>
      </div>
      <div class="footer"><span>Slide 6 / 6</span><strong>面试表达与交付物</strong></div>
    </section>
  </div>
  <script>
    const query = new URLSearchParams(window.location.search);
    const target = query.get("slide");
    const slides = Array.from(document.querySelectorAll(".slide"));
    if (target) {{
      slides.forEach((slide) => {{
        slide.classList.toggle("active", slide.dataset.slide === target);
      }});
    }} else {{
      slides.forEach((slide) => slide.classList.add("active"));
    }}
  </script>
</body>
</html>
"""


def render_pdf_and_screenshots(index_path: Path) -> None:
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        return

    pdf_path = PRESENTATION_DIR / "stock-rag-showcase.pdf"
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            f"--print-to-pdf={pdf_path}",
            str(index_path),
        ],
        check=True,
        cwd=PRESENTATION_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for slide_no in range(1, 7):
        shot_path = SCREENSHOT_DIR / f"slide-{slide_no}.png"
        subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--allow-file-access-from-files",
                "--window-size=1600,900",
                f"--screenshot={shot_path}",
                f"file://{index_path}?slide={slide_no}",
            ],
            check=True,
            cwd=PRESENTATION_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    answer_eval = run_json([sys.executable, "scripts/eval.py", "answer-full"])
    facts_eval = run_json([sys.executable, "scripts/eval_facts_gold.py", "--dataset", str(FACTS_DATASET)])
    audit = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))

    write_json(DATA_DIR / "answer-full.latest.json", answer_eval)
    write_json(DATA_DIR / "facts-gold.latest.json", facts_eval)
    write_json(DATA_DIR / "artifact-audit.latest.json", audit)

    answer = answer_eval["answer"]
    facts_before_accuracy = 162 / 208
    audit_rows = audit["rows"]
    total_fields = facts_eval["total_fields"]
    usable_fields = sum(len(row["usable_raw_metrics"]) + len(row["usable_derived_metrics"]) for row in audit_rows)
    missing_fields = sum(len(row["missing_metrics"]) for row in audit_rows)
    low_conf_fields = sum(len(row["low_confidence_metrics"]) for row in audit_rows)
    derived_fields = sum(len(row["derived_metrics"]) for row in audit_rows)

    build_accuracy_uplift_chart(
        before_acc=facts_before_accuracy,
        after_acc=facts_eval["field_accuracy"],
        exact_rate=facts_eval["document_exact_match_rate"],
        path=ASSETS_DIR / "accuracy_uplift.png",
    )
    build_field_breakdown_chart(facts_eval["field_breakdown"], ASSETS_DIR / "field_breakdown.png")
    build_calc_coverage_chart(
        total_fields=total_fields,
        usable_fields=usable_fields,
        low_conf=low_conf_fields,
        derived=derived_fields,
        missing=missing_fields,
        path=ASSETS_DIR / "calc_coverage.png",
    )

    context = {
        "metrics": [
            {
                "label": "问答回归通过率",
                "value": f'{answer["passed"]}/{answer["total"]}',
                "note": f'最新 `answer-full` 通过率 {percent(answer["pass_rate"])}。',
            },
            {
                "label": "结构化字段准确率",
                "value": f'{facts_eval["matched_fields"]}/{facts_eval["total_fields"]}',
                "note": f'人工真值字段准确率 {percent(facts_eval["field_accuracy"])}。',
            },
            {
                "label": "文档级完全命中",
                "value": f'{facts_eval["document_exact_matches"]}/{facts_eval["documents"]}',
                "note": f'26 份财报中有 {percent(facts_eval["document_exact_match_rate"])} 完全命中。',
            },
            {
                "label": "规则层放行字段",
                "value": f"{usable_fields}/{total_fields}",
                "note": f'规则层放行率 {usable_fields / total_fields * 100:.2f}%，仅表示 confidence/provenance 门禁通过；真实准确率以 199/208 为准。',
            },
        ],
        "engineering_bullets": [
            "统一为 `python scripts/eval.py` 入口，避免评测脚本散落。",
            "按 `smoke / full` 两层回归管理质量门禁。",
            "记录 query 级结构化日志，支持失败标注与重放。",
            "把 `facts` 评测从快照一致性推进到人工真值准确率。",
        ],
        "issue_bullets": [
            "银行类财报里的脚注编号 `（1）/（2）` 会被误识别成指标值。",
            "`净利润` 和 `经营现金流` 在多表场景里容易绑定到错误主行。",
            "同一份财报同时出现 `元 / 万元 / 百万元` 时，金额归一化会被放大或缩小。",
        ],
        "hook_bullets": [
            "我会先定义质量指标和评测集，再改抽取规则，而不是只做经验调参。",
            "系统输出带 provenance 和 usable 边界，适合接量化或估值模块。",
            "每次优化都能回溯到脚本、数据集和审计快照，便于协作和复盘。",
            "面对复杂财报格式，我会把问题落到规则、数据和验证机制三个层面解决。",
        ],
        "terminal_snippet": build_terminal_snippet(answer_eval, facts_eval),
        "artifact_snippet": build_artifact_snippet(audit_rows),
    }

    index_html = build_html(context)
    index_path = PRESENTATION_DIR / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    notes = dedent(
        f"""
        # Stock-RAG 演示说明

        - 打开 `presentation/index.html` 可以直接全屏展示。
        - `presentation/stock-rag-showcase.pdf` 是导出的演示文稿。
        - `presentation/screenshots/slide-*.png` 是每页截图。

        本次演示引用的数据来源：
        - `scripts/eval.py answer-full`
        - `scripts/eval_facts_gold.py --dataset tests/facts_eval_gold_manual_2026q1_26docs.json`
        - `data/audits/artifact_audit_20260516-facts-26docs.json`
        """
    ).strip()
    (PRESENTATION_DIR / "README.md").write_text(notes + "\n", encoding="utf-8")

    render_pdf_and_screenshots(index_path)
    print(str(PRESENTATION_DIR))


if __name__ == "__main__":
    main()
