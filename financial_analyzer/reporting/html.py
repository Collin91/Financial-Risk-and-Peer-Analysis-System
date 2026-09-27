"""Self-contained HTML summary page (charts embedded, no external assets).

Kept deliberately short: the verdict per company, the periods compared, the peer table
and a few key charts. Everything else (all charts, events, methodology) is collapsed.
"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

from financial_analyzer.analysis import risk
from financial_analyzer.analysis.metrics import METRICS_BY_KEY, format_value
from financial_analyzer.analysis.pipeline import PERIOD_DISCLOSURE
from financial_analyzer.data.standardize import long_date, short_date
from financial_analyzer.events import DISCLAIMER as EVENTS_DISCLAIMER

KEY_CHARTS = ("risk_score", "operating_margin", "revenue_growth", "fcf_margin")
REASONS_SHOWN = 3

LEVEL_CLASS = {"Lower Risk": "good", "Moderate Risk": "warning", "Elevated Risk": "critical"}
LEVEL_ICON = {"Lower Risk": "&#10003;", "Moderate Risk": "!", "Elevated Risk": "&#9888;"}

CSS = """
:root { --bg:#f6f5f2; --surface:#fcfcfb; --text:#0b0b0b; --muted:#52514e; --line:#e4e3df;
  --good:#0ca30c; --warning:#fab219; --critical:#d03b3b; --good-bg:#e5f4e5; --warning-bg:#fdf1d6;
  --critical-bg:#f9e1e1; --accent:#2a78d6; --link:#1f5fbf; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#121211; --surface:#1a1a19;
  --text:#ffffff; --muted:#c3c2b7; --line:#383835; --good-bg:#15301a; --warning-bg:#3a2e10;
  --critical-bg:#3b1a1a; --accent:#3987e5; --link:#86b6ef; color-scheme: dark; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1040px; margin:0 auto; padding:32px 16px 64px; }
h1 { font-size:28px; margin:0 0 4px; } h2 { font-size:20px; margin:36px 0 12px; }
a { color:var(--link); }
.meta, .muted { color:var(--muted); } .small { font-size:13px; }
.note { color:var(--muted); font-size:13px; margin:8px 0 0; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(290px,1fr)); gap:16px; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:18px; }
.card h3 { margin:0; font-size:18px; display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.period { font-size:13px; color:var(--muted); margin-top:2px; }
.badge { display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:999px; font-size:13px; font-weight:600; margin:10px 0 10px; }
.badge .icon { display:inline-grid; place-items:center; width:18px; height:18px; border-radius:50%; color:#fff; font-size:11px; }
.badge.good { background:var(--good-bg); } .badge.good .icon { background:var(--good); }
.badge.warning { background:var(--warning-bg); } .badge.warning .icon { background:var(--warning); color:#000; }
.badge.critical { background:var(--critical-bg); } .badge.critical .icon { background:var(--critical); }
.score { font-size:14px; color:var(--muted); font-weight:500; }
.card ul { margin:0; padding-left:18px; } .card li { margin:6px 0; }
.pts { font-variant-numeric:tabular-nums; color:var(--muted); font-size:13px; white-space:nowrap; }
.table-wrap { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:10px; }
table { border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums; }
th, td { padding:8px 12px; text-align:right; border-bottom:1px solid var(--line); white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
thead th { color:var(--muted); font-weight:600; font-size:13px; vertical-align:bottom; }
thead th .sub { display:block; font-weight:400; font-size:11px; }
tr:last-child td { border-bottom:none; }
td.target, th.target { background:color-mix(in srgb, var(--accent) 8%, transparent); font-weight:600; }
td.wrap { white-space:normal; text-align:left; min-width:300px; }
.better::after { content:" \\25B2"; color:var(--good); font-size:10px; }
.worse::after { content:" \\25BC"; color:var(--critical); font-size:10px; }
.charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:16px; margin-top:12px; }
.charts img { width:100%; height:auto; border:1px solid var(--line); border-radius:10px; background:#fcfcfb; display:block; }
ul.keep { padding-left:18px; } ul.keep li { margin:8px 0; }
ul.keep details { display:inline; } ul.keep summary { display:inline; cursor:pointer; color:var(--link); font-size:13px; }
ul.keep details[open] p { margin:6px 0 0; color:var(--muted); font-size:13px; }
details.section { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:12px 16px; margin-top:12px; }
details.section > summary { cursor:pointer; font-weight:600; }
@media (max-width:520px) { .charts { grid-template-columns:1fr; } h1 { font-size:22px; } }
"""


def _img(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return f'<img src="data:image/png;base64,{data}" alt="{escape(path.stem.replace("_", " "))} chart">'


def _table(head: list[str], rows: list[list[str]], head_classes: list[str] | None = None) -> str:
    head_classes = head_classes or [""] * len(head)
    ths = "".join(f'<th class="{c}">{h}</th>' if c else f"<th>{h}</th>" for h, c in zip(head, head_classes))
    body = "".join("<tr>" + "".join(row) + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div>'


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
        items = [f'<li>{escape(r.detail.split(" (comparability warning")[0])} '
                 f'<span class="pts" title="{escape(r.rule.id)} {escape(r.rule.name)}">+{r.points}</span></li>'
                 for r in fired[:REASONS_SHOWN]]
        if len(fired) > REASONS_SHOWN:
            items.append(f'<li class="muted">+{len(fired) - REASONS_SHOWN} more in the workbook</li>')
        if not fired:
            items += [f'<li class="muted">{escape(n)}</li>' for n in notes.get(name, [])[:1]] or \
                     ['<li class="muted">No warning signs triggered.</li>']
        tag = ' <span class="score">(target)</span>' if name == result.target else ""
        period = f'<div class="period">{p.label} · year ended {long_date(p.end)}</div>' if p else ""
        out.append(
            f'<article class="card"><h3><span>{escape(name)}{tag}</span><span class="score">{score} pts</span></h3>'
            f'{period}<span class="badge {LEVEL_CLASS[level]}"><span class="icon">{LEVEL_ICON[level]}</span>'
            f'{level}</span><ul>{"".join(items)}</ul></article>')
    return f'<div class="cards">{"".join(out)}</div>'


def _periods_table(result, year: int) -> str:
    rows = []
    for name in result.company_names:
        p = result.period(name, year)
        if p:
            rows.append([f"<td>{escape(name)}</td>", f"<td>{p.label}</td>", f"<td>{long_date(p.end)}</td>",
                         f"<td>{year}</td>"])
    return (_table(["Company", "Reported fiscal year", "Period ended", "Comparison year"], rows) +
            f'<p class="note">{escape(PERIOD_DISCLOSURE)}</p>')


def _peer_table(result) -> str:
    year = result.latest_year
    table = result.peer_comparison(year)
    head, classes = ["Metric"], [""]
    for c in table.columns:
        p = result.period(c, year)
        label = "Peer median" if c.startswith("Peer median") else escape(c)
        sub = f'<span class="sub">{p.label} · YE {short_date(p.end)}</span>' if p else '<span class="sub">excl. target</span>'
        head.append(f"{label}{sub}")
        classes.append("target" if c == result.target else "")
    rows = []
    for key, values in table.iterrows():
        metric = METRICS_BY_KEY[key]
        blocked = result.blocked(key, result.company_names)
        marker = result.peer_marker(key, year)
        cells = [f'<td title="{escape(metric.formula)}">{escape(metric.label)}{" †" if blocked else ""}</td>']
        for col, v in values.items():
            cls = ["target", marker] if col == result.target and marker else (["target"] if col == result.target else [])
            attr = f' class="{" ".join(cls)}"' if cls else ""
            cells.append(f"<td{attr}>{format_value(v, metric.fmt)}</td>")
        rows.append(cells)
    return (_table(head, rows, classes) +
            f'<p class="note">&#9650; / &#9660; {escape(result.target)} better / worse than the peer median. '
            f'† Not directly comparable across these companies (see "Keep in mind"). Hover a metric for its formula.</p>')


def _keep_in_mind(result) -> str:
    if not result.comparability:
        return '<p class="muted">No comparability issues detected.</p>'
    items = "".join(f'<li>{escape(w.summary or w.title)} <details><summary>More</summary><p>{escape(w.message)}</p>'
                    f'</details></li>' for w in result.comparability)
    return f'<ul class="keep">{items}</ul>'


def _events(result) -> str:
    if not result.events_run:
        return ""
    if not result.events:
        body = '<p class="muted">No candidate events matched the detected changes.</p>'
    else:
        rows = [[f"<td>{escape(e.company)}<br><span class='muted small'>{escape(e.reported_fiscal_year)}</span></td>",
                 f"<td>{escape(e.event_date)}</td>",
                 f'<td class="wrap">{escape(e.description)}<br><span class="muted small">Relates to: '
                 f'{escape(e.affected_metric)} · relevance {escape(e.relevance)}</span></td>',
                 f'<td><a href="{escape(e.url)}" rel="noopener">{escape(e.filing_type.split(" (")[0])}</a></td>']
                for e in result.events]
        body = _table(["Company", "Date", "What the filing says", "Source"], rows)
    return (f'<details class="section"><summary>Possible explanatory events from SEC filings ({len(result.events)})'
            f'</summary><p class="note">{escape(EVENTS_DISCLAIMER)}</p>{body}</details>')


def _methodology(result) -> str:
    families = " · ".join(f"<strong>{p}</strong> {escape(m.replace(' rules', '').lower())}"
                          for p, m in risk.RULE_FAMILIES.items())
    rules = "".join(f"<tr><td>{r.id}</td><td style='text-align:left'>{escape(r.name)}</td><td>{r.points}</td>"
                    f"<td class='wrap'>{escape(r.test)}</td></tr>" for r in result.profile.rules)
    data_notes = "".join(f"<li>{escape(w)}</li>" for w in result.warnings)
    return f"""
<details class="section"><summary>How the score works</summary>
<p class="small">Each rule below adds its points when it is triggered. 0-2 points = Lower Risk, 3-5 = Moderate, 6+ =
Elevated. Rules comparing against peers need at least {risk.MIN_PEERS} comparable peers to add points. The
workbook's <em>Rule Details</em> sheet shows every rule for every company and year.</p>
<p class="small">{families}</p>
<div class="table-wrap"><table><thead><tr><th>Rule</th><th style="text-align:left">Name</th><th>Points</th>
<th style="text-align:left">Test</th></tr></thead><tbody>{rules}</tbody></table></div></details>
<details class="section"><summary>Where the numbers come from</summary><ul class="small">
<li>Annual reports (10-K / 20-F) from SEC EDGAR, read from their XBRL data. Each company's own figures and
fiscal-year labels are kept; nothing is reclassified.</li>
<li>Ratios use each company's own currency. Dollar amounts use Federal Reserve exchange rates.</li>
<li>The workbook's <em>Data Lineage</em> sheet shows the exact filing and XBRL concept behind every number.</li>
{data_notes}</ul></details>"""


def write_summary_page(result, path: Path, chart_paths: dict[str, Path], notes: dict[str, list[str]]) -> Path:
    peers = ", ".join(n for n in result.company_names if n != result.target)
    year = result.latest_year
    key = "".join(_img(chart_paths[k]) for k in KEY_CHARTS if k in chart_paths)
    more = [p for k, p in chart_paths.items() if k not in KEY_CHARTS]
    more_html = (f'<details class="section"><summary>More charts ({len(more)})</summary><div class="charts">'
                 f'{"".join(_img(p) for p in more)}</div></details>' if more else "")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(result.target)} Risk Summary</title><style>{CSS}</style></head>
<body><main>
<h1>{escape(result.target)} vs {escape(peers)}</h1>
<div class="meta">{escape(result.profile.name)} · comparison years {result.first_year}-{result.last_year} ·
risk scores for {year}</div>
<p class="note">Flags point to unusual financial patterns worth a closer look. They are not a finding of fraud or
a share-price forecast.</p>

<h2>At a glance</h2>
{_cards(result, notes)}

<h2>Periods compared</h2>
{_periods_table(result, year)}

<h2>Key trends</h2>
<div class="charts">{key}</div>
{more_html}

<h2>Peer comparison</h2>
{_peer_table(result)}

<h2>Keep in mind</h2>
{_keep_in_mind(result)}

<h2>More detail</h2>
{_events(result)}
{_methodology(result)}
<p class="note">Full detail: <strong>financial_report.xlsx</strong> in this folder.</p>
</main></body></html>"""
    path.write_text(page, encoding="utf-8")
    return path
