# Stock-RAG Node Schema

## Purpose

This project exposes two post-ingest artifacts that can be consumed as workflow nodes:

- `extract_facts`
- `analyze_fundamentals`

The intended split is:

- `extract_facts`: structured report facts for machines and downstream calculators
- `analyze_fundamentals`: rule-based interpretation layer for screening and human review

## Lifecycle

Current pipeline:

1. download report PDF
2. parse report
3. extract metadata
4. chunk content
5. generate chunk embeddings
6. persist `documents` and `chunks`
7. generate and persist `document_artifacts`

Artifacts are stored in `document_artifacts.payload`.

## Artifact Types

### `extract_facts`

Top-level fields:

- `node_type`: always `extract_facts`
- `schema_version`: current version string, now `v1`
- `document_id`
- `company`
- `ticker`
- `report_period`
- `report_type`
- `basic_info`
- `facts`
- `metrics`
- `data_quality`

`basic_info` fields:

- `document_id`
- `title`
- `source`
- `company`
- `ticker`
- `industry`
- `published_at`
- `report_period`
- `report_type`
- `currency`
- `reported_unit`

Each item in `facts` contains:

- `metric`
- `display_name`
- `fact_origin`
- `term`
- `value`
- `numeric_value`
- `previous_value`
- `previous_numeric_value`
- `change_pct`
- `reported_unit`
- `currency`
- `normalized_value_cny`
- `scope`
- `source_page`
- `citation_title`
- `section_title`
- `table_title`
- `confidence`
- optional `quality_flag`
- optional `consistency_gap`

`metrics` is a keyed map:

- `metric_name -> fact object or null`

Current supported metric keys:

- `revenue`
- `net_profit_attributable`
- `net_profit`
- `total_assets`
- `total_liabilities`
- `equity_attributable`
- `operating_cash_flow`
- `eps_basic`

`data_quality` fields:

- `fact_count`
- `missing_metrics`
- `derived_metrics`

### `analyze_fundamentals`

Top-level fields:

- `node_type`: always `analyze_fundamentals`
- `schema_version`
- `document_id`
- `company`
- `ticker`
- `report_period`
- `basic_info`
- `snapshot`
- `ratios`
- `signals`
- `usable_for_calc`
- `data_quality`
- `summary`

`snapshot`:

- non-null subset of `extract_facts.metrics`

`ratios` currently may contain:

- `net_margin`
- `debt_to_assets`
- `operating_cashflow_margin`
- `equity_ratio`

Each item in `signals` contains:

- `name`
- `value`
- `detail`

Current signal names:

- `profitability`
- `leverage`
- `cashflow`

`usable_for_calc` fields:

- `raw_metrics`
- `derived_metrics`
- `excluded_metrics`

Meaning:

- `raw_metrics`: high-confidence raw extracted fields that can be used directly
- `derived_metrics`: derived fields that are still allowed into calculation
- `excluded_metrics`: fields withheld from calculation due to low confidence

`data_quality` fields:

- `available_metric_count`
- `missing_metrics`
- `low_confidence_metrics`
- `analysis_confidence_threshold`

`summary`:

- list of short rule-based findings for display and audit

## Semantic Flags

### `fact_origin`

Allowed values currently used:

- `raw_extracted`
- `derived`
- `downgraded_raw`

Interpretation:

- `raw_extracted`: extracted directly from report content
- `derived`: computed from other trusted fields
- `downgraded_raw`: extracted directly, but downgraded after consistency checks

### `quality_flag`

Current flags in use include:

- `derived_from_assets_minus_equity`
- `balance_sheet_inconsistent`
- `balance_sheet_gap`

These flags are intended for audit and downstream filtering, not for direct display to end users without explanation.

## Calculation Boundary

Downstream deterministic calculation nodes should prefer:

1. `usable_for_calc.raw_metrics`
2. `usable_for_calc.derived_metrics`

They should not directly consume:

- metrics listed in `usable_for_calc.excluded_metrics`

Recommended policy:

- use `raw_metrics` by default
- allow `derived_metrics` only when the downstream node keeps provenance
- treat `excluded_metrics` as review-only

## Example: `extract_facts`

```json
{
  "node_type": "extract_facts",
  "schema_version": "v1",
  "document_id": 54,
  "company": "恒力石化",
  "ticker": "600346",
  "report_period": "2026Q1",
  "report_type": "quarterly",
  "basic_info": {
    "title": "600346_恒力石化_2026_Q1报",
    "industry": "石油化工",
    "currency": "CNY",
    "reported_unit": "万元"
  },
  "data_quality": {
    "fact_count": 8,
    "missing_metrics": [],
    "derived_metrics": ["total_liabilities"]
  }
}
```

## Example: `analyze_fundamentals`

```json
{
  "node_type": "analyze_fundamentals",
  "schema_version": "v1",
  "document_id": 54,
  "company": "恒力石化",
  "ticker": "600346",
  "report_period": "2026Q1",
  "ratios": {
    "net_margin": 0.07949,
    "debt_to_assets": 0.744347
  },
  "usable_for_calc": {
    "raw_metrics": [
      "revenue",
      "total_assets",
      "equity_attributable"
    ],
    "derived_metrics": [
      "total_liabilities"
    ],
    "excluded_metrics": []
  }
}
```

## Recommended Downstream Contract

For workflow integration, downstream nodes should consume:

- `basic_info`
- `metrics`
- `usable_for_calc`

Minimal contract for a calculation node:

```json
{
  "document_id": 54,
  "ticker": "600346",
  "report_period": "2026Q1",
  "metrics": { "...": "..." },
  "usable_for_calc": {
    "raw_metrics": [],
    "derived_metrics": [],
    "excluded_metrics": []
  }
}
```

This keeps extraction, interpretation, and deterministic financial calculation separated.
