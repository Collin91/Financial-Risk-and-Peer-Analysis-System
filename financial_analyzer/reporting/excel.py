"""Formatted Excel workbook: risk summary, peer comparison, trends, rule detail, data and methodology."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .. import risk
from ..metrics import METRICS_BY_KEY
from ..standardize import LINE_ITEMS

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14)
SUBTITLE_FONT = Font(italic=True, color="52514E")
BOLD = Font(bold=True)
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
GOOD_FILL = PatternFill("solid", fgColor="E2F4E2")
BAD_FILL = PatternFill("solid", fgColor="FBE3E1")
LEVEL_FILLS = {
    "Lower Risk": PatternFill("solid", fgColor="C8EBC8"),
    "Moderate Risk": PatternFill("solid", fgColor="FDE7B0"),
    "Elevated Risk": PatternFill("solid", fgColor="F4C0BD"),
}
TRIGGERED_FILL = PatternFill("solid", fgColor="FBE3E1")

NUMBER_FORMATS = {"pct": "0.0%", "ratio": '0.00"x"', "days": '0" days"'}
# Differences: percentage metrics are shown in percentage points (value x 100).
DIFF_FORMATS = {"pct": '+0.0" pp";-0.0" pp"', "ratio": '+0.00"x";-0.00"x"', "days": '+0" days";-0" days"'}


def _header(ws: Worksheet, row: int, values: list, col: int = 1) -> None:
    for i, v in enumerate(values):
        c = ws.cell(row=row, column=col + i, value=v)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _widths(ws: Worksheet, widths: dict[int, float]) -> None:
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width


def _write_frame(ws: Worksheet, df: pd.DataFrame, start_row: int = 1, formats: dict[str, str] | None = None) -> int:
    _header(ws, start_row, list(df.columns))
    for r, row in enumerate(df.itertuples(index=False), start=start_row + 1):
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=None if pd.isna(value) else value)
            cell.border = BORDER
            if formats and df.columns[c - 1] in formats:
                cell.number_format = formats[df.columns[c - 1]]
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(df.columns))}{start_row + len(df)}"
    return start_row + len(df) + 1


def _summary_sheet(wb: Workbook, result, notes: dict[str, list[str]]) -> None:
    ws = wb.active
    ws.title = "Risk Summary"
    year = result.latest_year
    ws["A1"] = f"Financial Risk & Peer Analysis - {result.profile.name}"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = (f"Company investigated: {result.target}   |   Peers: "
                f"{', '.join(n for n in result.company_names if n != result.target)}   |   "
                f"Fiscal years {result.first_fy}-{result.last_fy}   |   Scores shown for FY{year}")
    ws["A2"].font = SUBTITLE_FONT
    ws["A3"] = ("Flags identify unusual financial patterns that may warrant further investigation. "
                "They are not a fraud determination or a share-price forecast.")
    ws["A3"].font = SUBTITLE_FONT

    row = 5
    latest = result.scores[result.scores.fiscal_year == year].set_index("company")
    ordered = sorted(result.company_names, key=lambda n: -latest.loc[n, "score"] if n in latest.index else 0)
    for name in ordered:
        if name not in latest.index:
            continue
        score, level = int(latest.loc[name, "score"]), latest.loc[name, "risk_level"]
        label = f"{name}{' (target)' if name == result.target else ''} - {level}"
        ws.cell(row=row, column=1, value=label).font = Font(bold=True, size=12)
        ws.cell(row=row, column=1).fill = LEVEL_FILLS[level]
        ws.cell(row=row, column=2, value=f"Score: {score} points").font = BOLD
        ws.cell(row=row, column=2).fill = LEVEL_FILLS[level]
        row += 1
        fired = [r for r in result.rule_results if r.company == name and r.fiscal_year == year and r.triggered]
        for r in sorted(fired, key=lambda r: -r.points):
            ws.cell(row=row, column=1, value=f"  • {r.detail}")
            ws.cell(row=row, column=2, value=f"+{r.points}  [{r.rule.id}] {r.rule.test}").font = SUBTITLE_FONT
            row += 1
        for note in notes.get(name, []):
            ws.cell(row=row, column=1, value=f"  • {note}").font = Font(color="1B6E1B")
            row += 1
        if not fired and not notes.get(name):
            ws.cell(row=row, column=1, value="  • No rules triggered.")
            row += 1
        row += 1

    ws.cell(row=row, column=1, value="Score history").font = Font(bold=True, size=12)
    row += 1
    history = result.scores.pivot(index="company", columns="fiscal_year", values="score").reindex(result.company_names)
    _header(ws, row, ["Company"] + [f"FY{y}" for y in history.columns])
    for name, values in history.iterrows():
        row += 1
        ws.cell(row=row, column=1, value=name)
        for i, v in enumerate(values, start=2):
            cell = ws.cell(row=row, column=i, value=None if pd.isna(v) else int(v))
            if not pd.isna(v):
                cell.fill = LEVEL_FILLS[risk.risk_level(int(v))]
            cell.alignment = Alignment(horizontal="center")
    ws.cell(row=row + 2, column=1, value="Bands: 0-2 Lower Risk, 3-5 Moderate Risk, 6+ Elevated Risk. "
                                          "See 'Risk Rules' for every test and 'Methodology' for definitions.").font = SUBTITLE_FONT
    _widths(ws, {1: 78, 2: 70, 3: 10, 4: 10, 5: 10, 6: 10, 7: 10})


def _peer_sheet(wb: Workbook, result) -> None:
    ws = wb.create_sheet("Peer Comparison")
    year = result.latest_year
    table = result.peer_comparison(year)
    ws["A1"] = f"Peer comparison - FY{year}"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = (f"Green / red shading marks whether {result.target} is better or worse than the median of its peers "
                "(for metrics with a clear direction).")
    ws["A2"].font = SUBTITLE_FONT
    cols = ["Metric"] + list(table.columns) + [f"{result.target} vs median", "Formula"]
    _header(ws, 4, cols)
    r = 4
    for key, values in table.iterrows():
        r += 1
        metric = METRICS_BY_KEY[key]
        fmt = NUMBER_FORMATS[metric.fmt]
        ws.cell(row=r, column=1, value=metric.label).font = BOLD
        for c, v in enumerate(values, start=2):
            cell = ws.cell(row=r, column=c, value=None if pd.isna(v) else float(v))
            cell.number_format = fmt
        tv, med = values.get(result.target), values["Peer median (excl. target)"]
        diff_cell = ws.cell(row=r, column=len(cols) - 1)
        if not (pd.isna(tv) or pd.isna(med)):
            diff_cell.value = float((tv - med) * (100 if metric.fmt == "pct" else 1))
            diff_cell.number_format = DIFF_FORMATS[metric.fmt]
            if metric.higher_is_better is not None and tv != med:
                better = (tv > med) == metric.higher_is_better
                ws.cell(row=r, column=2 + list(table.columns).index(result.target)).fill = GOOD_FILL if better else BAD_FILL
        ws.cell(row=r, column=len(cols), value=metric.formula).font = SUBTITLE_FONT
        for c in range(1, len(cols) + 1):
            ws.cell(row=r, column=c).border = BORDER

    r += 3
    ws.cell(row=r, column=1, value=f"{result.target} vs its own history (FY{year} vs FY{result.first_fy}-{year - 1})").font = TITLE_FONT
    r += 1
    hist = result.target_vs_history()
    _header(ws, r, ["Metric", f"FY{year}", "Prior average", "Prior low", "Prior high", "Change vs average"])
    for key, values in hist.iterrows():
        r += 1
        metric = METRICS_BY_KEY[key]
        fmt = NUMBER_FORMATS[metric.fmt]
        ws.cell(row=r, column=1, value=metric.label).font = BOLD
        for c, col in enumerate(["latest", "prior_average", "prior_min", "prior_max"], start=2):
            v = values[col]
            cell = ws.cell(row=r, column=c, value=None if pd.isna(v) else float(v))
            cell.number_format = fmt
        if not (pd.isna(values["latest"]) or pd.isna(values["prior_average"])):
            change = values["latest"] - values["prior_average"]
            cell = ws.cell(row=r, column=6, value=float(change * 100 if metric.fmt == "pct" else change))
            cell.number_format = DIFF_FORMATS[metric.fmt]
            if metric.higher_is_better is not None and change != 0:
                cell.fill = GOOD_FILL if (change > 0) == metric.higher_is_better else BAD_FILL
        for c in range(1, 7):
            ws.cell(row=r, column=c).border = BORDER
    _widths(ws, {1: 34, **{i: 16 for i in range(2, len(cols))}, len(cols): 60})


def _trends_sheet(wb: Workbook, result) -> None:
    ws = wb.create_sheet("Metric Trends")
    ws["A1"] = "Metric trends by company and fiscal year"
    ws["A1"].font = TITLE_FONT
    years = list(range(result.first_fy, result.last_fy + 1))
    r = 3
    for key in result.profile.metric_keys:
        metric = METRICS_BY_KEY[key]
        ws.cell(row=r, column=1, value=metric.label).font = Font(bold=True, size=12)
        ws.cell(row=r, column=2, value=metric.formula).font = SUBTITLE_FONT
        r += 1
        _header(ws, r, ["Company"] + [f"FY{y}" for y in years])
        for name in result.company_names:
            r += 1
            ws.cell(row=r, column=1, value=name).font = BOLD if name == result.target else Font()
            series = result.metrics.xs(name, level="company")[key]
            for c, y in enumerate(years, start=2):
                v = series.get(y)
                cell = ws.cell(row=r, column=c, value=None if v is None or pd.isna(v) else float(v))
                cell.number_format = NUMBER_FORMATS[metric.fmt]
                cell.border = BORDER
        r += 2
    _widths(ws, {1: 16, **{i: 13 for i in range(2, len(years) + 2)}})


def _rules_sheet(wb: Workbook, result) -> None:
    ws = wb.create_sheet("Risk Rules")
    df = risk.results_frame(result.rule_results).sort_values(["fiscal_year", "company", "rule_id"],
                                                               ascending=[False, True, True])
    ws["A1"] = "Every rule evaluated, for every company and year"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = "Filter the 'result' column to TRIGGERED to see only the warnings that added points."
    ws["A2"].font = SUBTITLE_FONT
    end = _write_frame(ws, df, start_row=4)
    for r in range(5, end):
        if ws.cell(row=r, column=6).value == "TRIGGERED":
            for c in range(1, len(df.columns) + 1):
                ws.cell(row=r, column=c).fill = TRIGGERED_FILL
    _widths(ws, {1: 12, 2: 11, 3: 9, 4: 17, 5: 62, 6: 12, 7: 8, 8: 11, 9: 80})


def _catalogue_rows(result) -> list[list]:
    return [[r.id, r.category, r.points, r.test] for r in result.profile.rules]


def _methodology_sheet(wb: Workbook, result) -> None:
    ws = wb.create_sheet("Methodology")
    ws["A1"] = "Methodology"
    ws["A1"].font = TITLE_FONT
    lines = [
        ("Data source", "Annual reports (10-K for US filers, 20-F for foreign filers) downloaded from SEC EDGAR. "
                        "Values are read from each filing's XBRL instance; only consolidated (non-segment) facts are used. "
                        "When a later filing restates a prior year, the most recently filed value is used."),
        ("Standardization", "Each line item has an ordered list of candidate XBRL concepts across US GAAP and IFRS. "
                            "The first concept reported for the year is used; documented derivations fill gaps. "
                            "The 'Data Lineage' sheet shows the exact concept, filing and FX rate behind every number."),
        ("Fiscal years", "Years ending January-May are labelled with the prior calendar year (e.g. Toyota's year ended "
                         "31 March 2026 is FY2025) so that most months overlap across companies."),
        ("Currency", "Ratios and growth rates are calculated in each company's reporting currency, so exchange-rate "
                     "moves do not distort them. USD amounts use Federal Reserve H.10 rates from FRED: period-average "
                     "rates for income and cash-flow items, period-end rates for balance-sheet items."),
        ("Peer median", "For each company, the median of the other companies in the comparison set for the same year."),
        ("Risk score", "Sum of the points for every triggered rule. 0-2 Lower Risk, 3-5 Moderate Risk, 6+ Elevated Risk."),
        ("Limitations", "The analysis flags unusual financial patterns for follow-up. It does not detect fraud, "
                        "assess management intent, or predict share prices. Accounting-policy differences between "
                        "US GAAP and IFRS remain even after label matching."),
    ]
    r = 3
    for title, text in lines:
        ws.cell(row=r, column=1, value=title).font = BOLD
        ws.cell(row=r, column=2, value=text).alignment = WRAP
        r += 1
    for note in result.profile.notes:
        ws.cell(row=r, column=1, value=f"{result.profile.name} caveat").font = BOLD
        ws.cell(row=r, column=2, value=note).alignment = WRAP
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="Metrics").font = Font(bold=True, size=12)
    r += 1
    _header(ws, r, ["Metric", "Formula"])
    for key in result.profile.metric_keys:
        r += 1
        ws.cell(row=r, column=1, value=METRICS_BY_KEY[key].label)
        ws.cell(row=r, column=2, value=METRICS_BY_KEY[key].formula)

    r += 2
    ws.cell(row=r, column=1, value="Rule catalogue").font = Font(bold=True, size=12)
    r += 1
    _header(ws, r, ["Rule", "Category", "Points", "Test"])
    for values in _catalogue_rows(result):
        r += 1
        for c, v in enumerate(values, start=1):
            ws.cell(row=r, column=c, value=v)

    r += 2
    ws.cell(row=r, column=1, value="Line items and candidate XBRL concepts").font = Font(bold=True, size=12)
    r += 1
    _header(ws, r, ["Line item", "Candidates (priority order)"])
    for item in LINE_ITEMS:
        r += 1
        ws.cell(row=r, column=1, value=item.label)
        ws.cell(row=r, column=2, value=", ".join(item.candidates)).alignment = WRAP

    if result.warnings:
        r += 2
        ws.cell(row=r, column=1, value="Data-quality notes").font = Font(bold=True, size=12)
        for w in result.warnings:
            r += 1
            ws.cell(row=r, column=2, value=w).alignment = WRAP
    _widths(ws, {1: 26, 2: 110, 3: 8, 4: 70})


def _charts_sheet(wb: Workbook, chart_paths: list[Path]) -> None:
    ws = wb.create_sheet("Charts")
    for i, path in enumerate(chart_paths):
        img = XLImage(str(path))
        img.width, img.height = 648, 342
        anchor_col = "A" if i % 2 == 0 else "L"
        ws.add_image(img, f"{anchor_col}{1 + (i // 2) * 18}")


def write_workbook(result, path: Path, chart_paths: list[Path], notes: dict[str, list[str]]) -> Path:
    wb = Workbook()
    _summary_sheet(wb, result, notes)
    _peer_sheet(wb, result)
    _trends_sheet(wb, result)
    _rules_sheet(wb, result)
    _charts_sheet(wb, chart_paths)

    ws = wb.create_sheet("Cleaned Financials")
    money = {c: '#,##0' for c in result.cleaned.columns if c.endswith("_usd_m")}
    money.update({"fx_avg_rate_per_usd": "0.00", "fx_period_end_rate_per_usd": "0.00"})
    _write_frame(ws, result.cleaned, formats=money)
    _widths(ws, {i: 15 for i in range(1, len(result.cleaned.columns) + 1)})

    ws = wb.create_sheet("Data Lineage")
    _write_frame(ws, result.lineage, formats={"native_value_m": "#,##0", "usd_value_m": "#,##0", "fx_rate_used": "0.00"})
    _widths(ws, {1: 12, 2: 11, 3: 22, 4: 15, 5: 9, 6: 12, 7: 14, 8: 15, 9: 80, 10: 24})

    _methodology_sheet(wb, result)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
