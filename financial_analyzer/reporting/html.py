"""Self-contained HTML risk-summary page (charts embedded, no external assets)."""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

import pandas as pd

from ..metrics import METRICS_BY_KEY, format_value

LEVEL_CLASS = {"Lower Risk": "good", "Moderate Risk": "warning", "Elevated Risk": "critical"}
LEVEL_ICON = {"Lower Risk": "&#10003;", "Moderate Risk": "!", "Elevated Risk": "&#9888;"}

CSS = """
:root { --bg:#f6f5f2; --surface:#fcfcfb; --text:#0b0b0b; --muted:#52514e; --line:#e4e3df;
  --good:#0ca30c; --warning:#fab219; --critical:#d03b3b; --good-bg:#e5f4e5; --warning-bg:#fdf1d6;
  --critical-bg:#f9e1e1; --accent:#2a78d6; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#121211; --surface:#1a1a19;
  --text:#ffffff; --muted:#c3c2b7; --line:#383835; --good-bg:#15301a; --warning-bg:#3a2e10;
  --critical-bg:#3b1a1a; --accent:#3987e5; color-scheme: dark; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1120px; margin:0 auto; padding:32px 16px 64px; }
h1 { font-size:28px; margin:0 0 4px; } h2 { font-size:20px; margin:40px 0 12px; }
.meta, .muted { color:var(--muted); } .small { font-size:13px; }
.disclaimer { border-left:3px solid var(--line); padding:8px 12px; margin:16px 0 0; color:var(--muted); font-size:13px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:18px; }
.card h3 { margin:0; font-size:18px; display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.badge { display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:999px; font-size:13px; font-weight:600; margin:10px 0 12px; }
.badge .icon { display:inline-grid; place-items:center; width:18px; height:18px; border-radius:50%; color:#fff; font-size:11px; }
.badge.good { background:var(--good-bg); } .badge.good .icon { background:var(--good); }
.badge.warning { background:var(--warning-bg); } .badge.warning .icon { background:var(--warning); color:#000; }
.badge.critical { background:var(--critical-bg); } .badge.critical .icon { background:var(--critical); }
.score { font-size:14px; color:var(--muted); font-weight:500; }
.card ul { margin:0; padding-left:18px; } .card li { margin:6px 0; }
.pts { font-variant-numeric:tabular-nums; font-weight:600; }
.rule { color:var(--muted); font-size:12px; display:block; }
.ok { color:var(--muted); }
.table-wrap { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:10px; }
table { border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums; }
th, td { padding:8px 12px; text-align:right; border-bottom:1px solid var(--line); white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
thead th { color:var(--muted); font-weight:600; font-size:13px; }
tr:last-child td { border-bottom:none; }
td.target, th.target { background:color-mix(in srgb, var(--accent) 8%, transparent); font-weight:600; }
.better::after { content:" \\25B2"; color:var(--good); font-size:10px; }
.worse::after { content:" \\25BC"; color:var(--critical); font-size:10px; }
.charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:16px; }
.charts img { width:100%; height:auto; border:1px solid var(--line); border-radius:10px; background:#fcfcfb; display:block; }
details { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:12px 16px; margin-top:12px; }
summary { cursor:pointer; font-weight:600; }
@media (max-width:520px) { .charts { grid-template-columns:1fr; } h1 { font-size:22px; } }
"""


def _img(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return f'<img src="data:image/png;base64,{data}" alt="{escape(path.stem.replace("_", " "))} chart">'


def _cards(result, notes: dict[str, list[str]]) -> str:
    year = result.latest_year
    latest = result.scores[result.scores.fiscal_year == year].set_index("company")
    names = sorted((n for n in result.company_names if n in latest.index), key=lambda n: -latest.loc[n, "score"])
    out = []
    for name in names:
        score, level = int(latest.loc[name, "score"]), latest.loc[name, "risk_level"]
        fired = sorted((r for r in result.rule_results if r.company == name and r.fiscal_year == year and r.triggered),
                       key=lambda r: -r.points)
        items = [f'<li>{escape(r.detail)} <span class="pts">+{r.points}</span>'
                 f'<span class="rule">{r.rule.id} · {escape(r.rule.test)}</span></li>' for r in fired]
        items += [f'<li class="ok">{escape(n)}</li>' for n in notes.get(name, [])]
        if not items:
            items = ['<li class="ok">No rules triggered.</li>']
        tag = ' <span class="score">(target)</span>' if name == result.target else ""
        out.append(
            f'<article class="card"><h3><span>{escape(name)}{tag}</span><span class="score">{score} pts</span></h3>'
            f'<span class="badge {LEVEL_CLASS[level]}"><span class="icon">{LEVEL_ICON[level]}</span>{level}</span>'
            f'<ul>{"".join(items)}</ul></article>')
    return f'<div class="cards">{"".join(out)}</div>'


def _history_table(result) -> str:
    pivot = result.scores.pivot(index="company", columns="fiscal_year", values="score").reindex(result.company_names)
    head = "".join(f"<th>FY{y}</th>" for y in pivot.columns)
    rows = []
    for name, values in pivot.iterrows():
        cells = "".join("<td>n/a</td>" if pd.isna(v) else f"<td>{int(v)}</td>" for v in values)
        cls = ' class="target"' if name == result.target else ""
        rows.append(f"<tr><td{cls}>{escape(name)}</td>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr><th>Company</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _peer_table(result) -> str:
    year = result.latest_year
    table = result.peer_comparison(year)
    median_col = "Peer median (excl. target)"
    head = "".join(f'<th class="target">{escape(c)}</th>' if c == result.target else f"<th>{escape(c)}</th>"
                   for c in table.columns)
    rows = []
    for key, values in table.iterrows():
        metric = METRICS_BY_KEY[key]
        cells = []
        for col, v in values.items():
            cls = []
            if col == result.target:
                cls.append("target")
                med = values[median_col]
                if metric.higher_is_better is not None and not (pd.isna(v) or pd.isna(med)) and v != med:
                    cls.append("better" if (v > med) == metric.higher_is_better else "worse")
            attr = f' class="{" ".join(cls)}"' if cls else ""
            cells.append(f"<td{attr}>{format_value(v, metric.fmt)}</td>")
        rows.append(f'<tr><td title="{escape(metric.formula)}">{escape(metric.label)}</td>{"".join(cells)}</tr>')
    return (f'<div class="table-wrap"><table><thead><tr><th>Metric (FY{year})</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
            f'<p class="small muted">&#9650; / &#9660; mark whether {escape(result.target)} is better or worse than '
            f'the median of its peers. Hover a metric name for its formula.</p>')


def _methodology(result) -> str:
    rules = "".join(f"<tr><td>{r.id}</td><td>{escape(r.category)}</td><td>{r.points}</td><td style='text-align:left'>"
                    f"{escape(r.test)}</td></tr>" for r in result.profile.rules)
    caveats = "".join(f"<li>{escape(n)}</li>" for n in result.profile.notes)
    warnings = "".join(f"<li>{escape(w)}</li>" for w in result.warnings) or "<li>None.</li>"
    return f"""
<details><summary>Rule catalogue ({len(result.profile.rules)} rules)</summary>
<div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>Rule</th><th>Category</th><th>Points</th>
<th style="text-align:left">Test</th></tr></thead><tbody>{rules}</tbody></table></div>
<p class="small muted">Score bands: 0-2 Lower Risk, 3-5 Moderate Risk, 6+ Elevated Risk. Peer median = median of the
other companies in the set for the same fiscal year.</p></details>
<details><summary>How the data was prepared</summary><ul>
<li>Annual reports (10-K / 20-F) are downloaded from SEC EDGAR and read from their XBRL instance documents.
Only consolidated, non-segment facts are used; restated figures from later filings replace earlier ones.</li>
<li>Different accounting labels (US GAAP and IFRS concepts) are mapped onto one set of line items; the Excel
report's <em>Data Lineage</em> sheet shows the concept and filing behind every number.</li>
<li>Ratios and growth rates use each company's reporting currency. USD amounts use Federal Reserve H.10 rates
(period average for flows, period end for balances).</li>
<li>Fiscal years ending January-May are labelled with the prior calendar year.</li></ul></details>
<details><summary>{escape(result.profile.name)} caveats</summary><ul>{caveats or '<li>None.</li>'}</ul></details>
<details><summary>Data-quality notes</summary><ul>{warnings}</ul></details>"""


def write_summary_page(result, path: Path, chart_paths: list[Path], notes: dict[str, list[str]]) -> Path:
    peers = ", ".join(n for n in result.company_names if n != result.target)
    charts = "".join(_img(p) for p in chart_paths)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(result.target)} Risk Summary</title><style>{CSS}</style></head>
<body><main>
<h1>{escape(result.target)} - Financial Risk &amp; Peer Analysis</h1>
<div class="meta">{escape(result.profile.name)} · compared with {escape(peers)} · FY{result.first_fy}-FY{result.last_fy}
· scores for FY{result.latest_year}</div>
<p class="disclaimer">Flags identify unusual financial patterns that may warrant further investigation. Each point
comes from a defined accounting rule listed below. This is not a fraud determination or a share-price forecast.</p>
<h2>Risk summary</h2>
{_cards(result, notes)}
<h2>Score history</h2>
{_history_table(result)}
<h2>Peer comparison</h2>
{_peer_table(result)}
<h2>Trends</h2>
<div class="charts">{charts}</div>
<h2>Methodology</h2>
{_methodology(result)}
</main></body></html>"""
    path.write_text(page, encoding="utf-8")
    return path
