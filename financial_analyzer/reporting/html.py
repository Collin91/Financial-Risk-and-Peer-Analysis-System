"""Self-contained HTML risk-summary page (charts embedded, no external assets)."""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

from .. import risk
from ..analysis import PERIOD_DISCLOSURE
from ..events import DISCLAIMER as EVENTS_DISCLAIMER
from ..metrics import METRICS_BY_KEY, format_value
from ..standardize import long_date, short_date

LEVEL_CLASS = {"Lower Risk": "good", "Moderate Risk": "warning", "Elevated Risk": "critical"}
LEVEL_ICON = {"Lower Risk": "&#10003;", "Moderate Risk": "!", "Elevated Risk": "&#9888;"}

CSS = """
:root { --bg:#f6f5f2; --surface:#fcfcfb; --text:#0b0b0b; --muted:#52514e; --line:#e4e3df;
  --good:#0ca30c; --warning:#fab219; --critical:#d03b3b; --good-bg:#e5f4e5; --warning-bg:#fdf1d6;
  --critical-bg:#f9e1e1; --info-bg:#eef2f7; --accent:#2a78d6; --link:#1f5fbf; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#121211; --surface:#1a1a19;
  --text:#ffffff; --muted:#c3c2b7; --line:#383835; --good-bg:#15301a; --warning-bg:#3a2e10;
  --critical-bg:#3b1a1a; --info-bg:#1f2630; --accent:#3987e5; --link:#86b6ef; color-scheme: dark; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1120px; margin:0 auto; padding:32px 16px 64px; }
h1 { font-size:28px; margin:0 0 4px; } h2 { font-size:20px; margin:40px 0 12px; }
a { color:var(--link); }
.meta, .muted { color:var(--muted); } .small { font-size:13px; }
.disclaimer { border-left:3px solid var(--line); padding:8px 12px; margin:16px 0 0; color:var(--muted); font-size:13px; }
.disclosure { border-left:3px solid var(--accent); padding:8px 12px; margin:12px 0; font-size:14px; background:var(--surface); }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:18px; }
.card h3 { margin:0; font-size:18px; display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.period { font-size:13px; color:var(--muted); margin-top:2px; }
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
.warn { background:var(--warning-bg); border-radius:10px; padding:12px 16px; margin:10px 0; font-size:14px; }
.warn strong { display:block; margin-bottom:4px; }
.table-wrap { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:10px; }
table { border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums; }
th, td { padding:8px 12px; text-align:right; border-bottom:1px solid var(--line); white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
thead th { color:var(--muted); font-weight:600; font-size:13px; vertical-align:bottom; }
thead th .sub { display:block; font-weight:400; font-size:11px; }
tr:last-child td { border-bottom:none; }
td.target, th.target { background:color-mix(in srgb, var(--accent) 8%, transparent); font-weight:600; }
td.wrap { white-space:normal; text-align:left; min-width:320px; }
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


def _table(head: list[str], rows: list[list[str]], head_classes: list[str] | None = None) -> str:
    head_classes = head_classes or [""] * len(head)
    ths = "".join(f'<th class="{c}">{h}</th>' if c else f"<th>{h}</th>" for h, c in zip(head, head_classes))
    body = "".join("<tr>" + "".join(rows_cell for rows_cell in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div>'


def _periods_table(result, year: int) -> str:
    rows = []
    for name in result.company_names:
        p = result.period(name, year)
        if p:
            rows.append([f"<td>{escape(name)}</td>", f"<td>{p.label}</td>", f"<td>{long_date(p.end)}</td>",
                         f"<td>{year}</td>"])
    return _table(["Company", "Reported fiscal year", "Period ended", "Comparison year"], rows)


def _cards(result, notes: dict[str, list[str]]) -> str:
    year = result.latest_year
    latest = result.scores[result.scores.comparison_year == year].set_index("company")
    names = sorted((n for n in result.company_names if n in latest.index), key=lambda n: -latest.loc[n, "score"])
    out = []
    for name in names:
        score, level = int(latest.loc[name, "score"]), latest.loc[name, "risk_level"]
        p = result.period(name, year)
        fired = sorted((r for r in result.rule_results if r.company == name and r.comparison_year == year and r.triggered),
                       key=lambda r: -r.points)
        items = [f'<li>{escape(r.detail)} <span class="pts">+{r.points}</span>'
                 f'<span class="rule">{r.rule.id} {escape(r.rule.name)} · {escape(r.rule.test)}</span></li>'
                 for r in fired]
        items += [f'<li class="ok">{escape(n)}</li>' for n in notes.get(name, [])]
        if not items:
            items = ['<li class="ok">No rules triggered.</li>']
        tag = ' <span class="score">(target)</span>' if name == result.target else ""
        period = (f'<div class="period">{p.label} · Year ended {long_date(p.end)} · Comparison period: {year}</div>'
                  if p else "")
        out.append(
            f'<article class="card"><h3><span>{escape(name)}{tag}</span><span class="score">{score} pts</span></h3>'
            f'{period}<span class="badge {LEVEL_CLASS[level]}"><span class="icon">{LEVEL_ICON[level]}</span>'
            f'{level}</span><ul>{"".join(items)}</ul></article>')
    return f'<div class="cards">{"".join(out)}</div>'


def _warnings(result) -> str:
    return "".join(f'<div class="warn"><strong>{"† " if w.suppresses_peer_points else ""}{escape(w.title)}</strong>'
                   f'{escape(w.message)}</div>' for w in result.comparability)


def _history_table(result) -> str:
    years = list(result.years)
    history = result.scores.set_index(["company", "comparison_year"])
    rows = []
    for name in result.company_names:
        cls = ' class="target"' if name == result.target else ""
        cells = [f"<td{cls}>{escape(name)}</td>"]
        for y in years:
            p = result.period(name, y)
            if (name, y) in history.index and p:
                cells.append(f'<td title="{p.label}, year ended {long_date(p.end)}">'
                             f'{int(history.loc[(name, y), "score"])} <span class="muted small">({p.label})</span></td>')
            else:
                cells.append("<td>n/a</td>")
        rows.append(cells)
    return (_table(["Company"] + [f"Comparison year {y}" for y in years], rows) +
            '<p class="small muted">Each cell shows the score and the company\'s reported fiscal year placed in that '
            'comparison year.</p>')


def _peer_table(result) -> str:
    year = result.latest_year
    table = result.peer_comparison(year)
    head, classes = [f"Metric (comparison year {year})"], [""]
    for c in table.columns:
        p = result.period(c, year)
        sub = f'<span class="sub">{p.label} · YE {short_date(p.end)}</span>' if p else ""
        head.append(f"{escape(c)}{sub}")
        classes.append("target" if c == result.target else "")
    rows = []
    for key, values in table.iterrows():
        metric = METRICS_BY_KEY[key]
        blocked = result.blocked(key, result.company_names)
        marker = result.peer_marker(key, year)
        cells = [f'<td title="{escape(metric.formula)}">{escape(metric.label)}{" †" if blocked else ""}</td>']
        for col, v in values.items():
            cls = []
            if col == result.target:
                cls.append("target")
                if marker:
                    cls.append(marker)
            attr = f' class="{" ".join(cls)}"' if cls else ""
            cells.append(f"<td{attr}>{format_value(v, metric.fmt)}</td>")
        rows.append(cells)
    return (_table(head, rows, classes) +
            f'<p class="small muted">&#9650; / &#9660; mark whether {escape(result.target)} is better or worse than the '
            f'median of its peers; no marker when values match at report precision. † = not directly comparable across '
            f'these companies (see the warnings above); shown for information and assigns no peer-based points. '
            f'Hover a metric name for its formula.</p>')


def _events(result) -> str:
    intro = f'<p class="disclaimer">{escape(EVENTS_DISCLAIMER)}</p>'
    if not result.events_run:
        return intro + '<p class="muted">Event retrieval was not run for this report.</p>'
    errs = "".join(f'<p class="small muted">Retrieval note: {escape(e)}</p>' for e in result.event_errors)
    if not result.events:
        return intro + errs + '<p class="muted">No candidate events matched the detected changes.</p>'
    rows = [[f"<td>{escape(e.company)}</td>",
             f"<td>{escape(e.reported_fiscal_year)}</td>",
             f"<td>{escape(e.event_date)}</td>",
             f'<td class="wrap">{escape(e.description)}</td>',
             f"<td>{escape(e.relevance)}</td>",
             f"<td>{escape(e.affected_metric)}</td>",
             f'<td><a href="{escape(e.url)}" rel="noopener">{escape(e.filing_type)}</a></td>']
            for e in result.events]
    return intro + errs + _table(["Company", "Fiscal year", "Event date", "Description", "Relevance",
                                  "Affected metric", "SEC source"], rows)


def _methodology(result) -> str:
    families = "".join(f"<li><strong>{p}</strong> - {escape(m)}</li>" for p, m in risk.RULE_FAMILIES.items())
    rules = "".join(f"<tr><td>{r.id}</td><td style='text-align:left'>{escape(r.name)}</td><td>{r.points}</td>"
                    f"<td style='text-align:left;white-space:normal'>{escape(r.test)}</td></tr>"
                    for r in result.profile.rules)
    notes = "".join(f"<li>{escape(n)}</li>" for n in result.profile.notes)
    warnings = "".join(f"<li>{escape(w)}</li>" for w in result.warnings) or "<li>None.</li>"
    return f"""
<details><summary>Rule catalogue ({len(result.profile.rules)} rules)</summary>
<ul class="small">{families}</ul>
<div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>Rule</th><th style="text-align:left">Name</th>
<th>Points</th><th style="text-align:left">Test</th></tr></thead><tbody>{rules}</tbody></table></div>
<p class="small muted">Score bands: 0-2 Lower Risk, 3-5 Moderate Risk, 6+ Elevated Risk. Peer median = median of the
other companies for the same comparison year. Peer-based rules assign points only with at least {risk.MIN_PEERS} usable,
comparable peer values; otherwise they are informational.</p></details>
<details><summary>How the data was prepared</summary><ul>
<li>Annual reports (10-K / 20-F) are downloaded from SEC EDGAR and read from their XBRL instance documents.
Only consolidated, non-segment facts are used; restated figures from later filings replace earlier ones.</li>
<li>Each company's reported fiscal-year label comes from its own filing and is never changed. {escape(PERIOD_DISCLOSURE)}</li>
<li>US GAAP and IFRS concepts are mapped onto one set of line items without reclassifying any company's figures; the
Excel report's <em>Data Lineage</em> sheet shows the concept and filing behind every number.</li>
<li>Capital expenditures are cash paid for purchases of property, plant and equipment for every company; intangible
assets, leased-vehicle purchases, acquisitions and finance receivables are excluded.</li>
<li>Ratios and growth rates use each company's reporting currency. USD amounts use Federal Reserve H.10 rates
(period average for flows, period end for balances).</li></ul></details>
<details><summary>{escape(result.profile.name)} notes</summary><ul>{notes or '<li>None.</li>'}</ul></details>
<details><summary>Data-quality notes</summary><ul>{warnings}</ul></details>"""


def write_summary_page(result, path: Path, chart_paths: list[Path], notes: dict[str, list[str]]) -> Path:
    peers = ", ".join(n for n in result.company_names if n != result.target)
    year = result.latest_year
    charts = "".join(_img(p) for p in chart_paths)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(result.target)} Risk Summary</title><style>{CSS}</style></head>
<body><main>
<h1>{escape(result.target)} - Financial Risk &amp; Peer Analysis</h1>
<div class="meta">{escape(result.profile.name)} · compared with {escape(peers)} · comparison years
{result.first_year}-{result.last_year} · scores for comparison year {year}
({escape(result.target)} {escape(result.period_label(result.target, year))})</div>
<p class="disclaimer">Flags identify unusual financial patterns that may warrant further investigation. Each point
comes from a defined accounting rule listed below. This is not a fraud determination or a share-price forecast.</p>
<h2>Periods compared</h2>
<p class="disclosure">{escape(PERIOD_DISCLOSURE)}</p>
{_periods_table(result, year)}
<h2>Risk summary</h2>
{_cards(result, notes)}
<h2>Data-comparability warnings</h2>
{_warnings(result) or '<p class="muted">None.</p>'}
<h2>Score history</h2>
{_history_table(result)}
<h2>Peer comparison</h2>
{_peer_table(result)}
<h2>Potential Explanatory Events</h2>
{_events(result)}
<h2>Trends</h2>
<div class="charts">{charts}</div>
<h2>Methodology</h2>
{_methodology(result)}
</main></body></html>"""
    path.write_text(page, encoding="utf-8")
    return path
