"""Write every output for an analysis run into one folder:

    summary.html                 one-page summary (start here)
    financial_report.xlsx        full workbook
    cleaned_financial_data.csv   standardized financial statements
    charts/                      trend charts (PNG)
    data/                        metrics, every rule result, explanatory events (CSV)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from financial_analyzer.analysis import risk
from financial_analyzer.reporting import charts, excel, html


def generate_outputs(result, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = out_dir / "data"
    data_dir.mkdir(exist_ok=True)
    chart_dir = out_dir / "charts"
    chart_dir.mkdir(exist_ok=True)
    chart_paths = {"risk_score": charts.score_chart(result, chart_dir), **charts.metric_charts(result, chart_dir)}

    year = result.latest_year
    notes = {name: risk.stability_notes(result.metrics, result.rule_results, name, year)
             for name in result.company_names}

    csv_path = out_dir / "cleaned_financial_data.csv"
    result.cleaned.to_csv(csv_path, index=False, float_format="%.2f")

    metrics = result.metrics[result.profile.metric_keys].reset_index()
    ids = result.periods[["company", "comparison_year", "reported_fiscal_year", "period_start", "period_end"]]
    metrics = ids.merge(metrics, on=["company", "comparison_year"], how="right")
    metrics = metrics[["company", "reported_fiscal_year", "period_start", "period_end", "comparison_year",
                       *result.profile.metric_keys]]
    metrics.to_csv(data_dir / "metrics.csv", index=False, float_format="%.4f")
    risk.results_frame(result.rule_results).to_csv(data_dir / "risk_rule_results.csv", index=False)
    if result.events_run:
        pd.DataFrame([vars(e) for e in result.events]).to_csv(data_dir / "explanatory_events.csv", index=False)

    return {
        "summary": html.write_summary_page(result, out_dir / "summary.html", chart_paths, notes),
        "excel": excel.write_workbook(result, out_dir / "financial_report.xlsx", notes),
        "cleaned_csv": csv_path,
        "data": data_dir,
        "charts": chart_dir,
    }
