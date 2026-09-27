"""Write every output for an analysis run into one folder."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import risk
from . import charts, excel, html


def generate_outputs(result, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    chart_dir = out_dir / "charts"
    metric_paths = charts.metric_charts(result, chart_dir)
    score_path = charts.score_chart(result, chart_dir)
    chart_list = [score_path, *metric_paths.values()]

    year = result.latest_year
    notes = {name: risk.stability_notes(result.metrics, result.rule_results, name, year)
             for name in result.company_names}

    csv_path = out_dir / "cleaned_financial_data.csv"
    result.cleaned.to_csv(csv_path, index=False, float_format="%.2f")

    metrics_path = out_dir / "metrics.csv"
    metrics = result.metrics[result.profile.metric_keys].reset_index()
    ids = result.periods[["company", "comparison_year", "reported_fiscal_year", "period_start", "period_end"]]
    metrics = ids.merge(metrics, on=["company", "comparison_year"], how="right")
    metrics = metrics[["company", "reported_fiscal_year", "period_start", "period_end", "comparison_year",
                       *result.profile.metric_keys]]
    metrics.to_csv(metrics_path, index=False, float_format="%.4f")

    rules_path = out_dir / "risk_rule_results.csv"
    risk.results_frame(result.rule_results).to_csv(rules_path, index=False)

    paths = {
        "excel": excel.write_workbook(result, out_dir / "financial_risk_report.xlsx", chart_list, notes),
        "summary": html.write_summary_page(result, out_dir / "risk_summary.html", chart_list, notes),
        "cleaned_csv": csv_path,
        "metrics_csv": metrics_path,
        "rules_csv": rules_path,
    }
    if result.events_run:
        events_path = out_dir / "explanatory_events.csv"
        pd.DataFrame([vars(e) for e in result.events]).to_csv(events_path, index=False)
        paths["events_csv"] = events_path
    paths["charts"] = chart_dir
    return paths
