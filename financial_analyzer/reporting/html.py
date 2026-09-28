"""Self-contained HTML summary page (no external assets; works offline).

Layout: header, risk at a glance (one card per company with a score meter), a snapshot of
the target's key numbers, periods compared, interactive trend charts, the peer table,
comparability notes, and collapsed detail sections.
"""

from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path

from financial_analyzer.analysis import risk
from financial_analyzer.analysis.metrics import METRICS_BY_KEY, displays_equal, format_value
from financial_analyzer.analysis.pipeline import PERIOD_DISCLOSURE
from financial_analyzer.data.standardize import long_date, short_date
from financial_analyzer.events import DISCLAIMER as EVENTS_DISCLAIMER
from financial_analyzer.reporting import svg

KEY_CHARTS = ("operating_margin", "revenue_growth", "fcf_margin")
SNAPSHOT_METRICS = ("revenue_growth", "operating_margin", "fcf_margin", "current_ratio")
REASONS_SHOWN = 3
METER_CELLS = 10

LEVEL_CLASS = {"Lower Risk": "good", "Moderate Risk": "warning", "Elevated Risk": "critical"}
LEVEL_ICON = {"Lower Risk": "&#10003;", "Moderate Risk": "!", "Elevated Risk": "&#9888;"}

_SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
_SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]


def _vars(values: list[str]) -> str:
    return " ".join(f"--s{i}:{v};" for i, v in enumerate(values, 1))


_DARK = f"""--bg:#111110; --surface:#1a1a19; --surface-2:#222220; --text:#f4f3ef; --muted:#b5b4ab; --faint:#8a897f;
  --line:#34342f; --grid:#2c2c28; --track:#34342f; --accent:#3987e5; --accent-bg:#172536; --link:#86b6ef;
  --good-bg:#15301a; --warning-bg:#3a2e10; --critical-bg:#3b1a1a; --note-bg:#1f2630; {_vars(_SERIES_DARK)}
  color-scheme:dark;"""

CSS = f"""
:root {{ --bg:#f5f4f0; --surface:#fcfcfb; --surface-2:#f1f0ec; --text:#141413; --muted:#5b5a55; --faint:#8a8983;
  --line:#e2e1dc; --grid:#ebeae6; --track:#e7e6e1; --accent:#2a78d6; --accent-bg:#eaf2fc; --link:#1f5fbf;
  --good:#0ca30c; --warning:#fab219; --critical:#d03b3b; --good-bg:#e5f4e5; --warning-bg:#fdf1d6;
  --critical-bg:#f9e1e1; --note-bg:#eef2f7; {_vars(_SERIES_LIGHT)} color-scheme:light; }}
@media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) {{ {_DARK} }} }}
:root[data-theme="dark"] {{ {_DARK} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; -webkit-font-smoothing:antialiased; }}
a {{ color:var(--link); }}
.wrap {{ max-width:1080px; margin:0 auto; padding:0 20px; }}
header.top {{ background:var(--surface); border-bottom:1px solid var(--line); padding:28px 0 0; }}
.eyebrow {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:600; }}
h1 {{ font-size:32px; line-height:1.2; margin:6px 0 6px; letter-spacing:-.01em; }}
h1 .vs {{ color:var(--faint); font-weight:400; }}
.lede {{ color:var(--muted); margin:0 0 18px; }}
nav.sections {{ display:flex; gap:4px; flex-wrap:wrap; }}
nav.sections a {{ color:var(--muted); text-decoration:none; font-size:14px; padding:8px 12px; border-bottom:2px solid transparent; }}
nav.sections a:hover {{ color:var(--text); border-bottom-color:var(--accent); }}
section {{ margin:40px 0 0; scroll-margin-top:16px; }}
h2 {{ font-size:20px; margin:0 0 4px; letter-spacing:-.005em; }}
.sub {{ color:var(--muted); font-size:14px; margin:0 0 16px; }}
.muted {{ color:var(--muted); }} .small {{ font-size:13px; }}
.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; }}

/* risk cards */
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr)); gap:16px; }}
.card {{ padding:20px; display:flex; flex-direction:column; gap:10px; }}
.card.is-target {{ border-color:var(--accent); box-shadow:0 0 0 1px var(--accent) inset; }}
.card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }}
.card-name {{ font-size:19px; font-weight:650; }}
.tag {{ font-size:11px; font-weight:600; color:var(--accent); background:var(--accent-bg); border-radius:999px;
  padding:2px 8px; margin-left:6px; vertical-align:3px; }}
.period {{ font-size:13px; color:var(--muted); }}
.score {{ text-align:right; line-height:1; }}
.score b {{ font-size:30px; font-weight:650; }} .score span {{ font-size:13px; color:var(--muted); }}
.badge {{ align-self:flex-start; display:inline-flex; align-items:center; gap:6px; padding:3px 10px 3px 4px;
  border-radius:999px; font-size:13px; font-weight:600; }}
.badge .icon {{ display:inline-grid; place-items:center; width:18px; height:18px; border-radius:50%; color:#fff; font-size:11px; }}
.badge.good {{ background:var(--good-bg); }} .badge.good .icon {{ background:var(--good); }}
.badge.warning {{ background:var(--warning-bg); }} .badge.warning .icon {{ background:var(--warning); color:#000; }}
.badge.critical {{ background:var(--critical-bg); }} .badge.critical .icon {{ background:var(--critical); }}
.meter {{ display:grid; grid-template-columns:repeat({METER_CELLS},1fr); gap:3px; }}
.meter i {{ height:8px; border-radius:2px; background:var(--track); }}
.meter.good i.on {{ background:var(--good); }} .meter.warning i.on {{ background:var(--warning); }}
.meter.critical i.on {{ background:var(--critical); }}
.meter-scale {{ display:grid; grid-template-columns:3fr 3fr 4fr; font-size:11px; color:var(--faint); margin-top:-4px; }}
.reasons {{ list-style:none; margin:4px 0 0; padding:0; display:flex; flex-direction:column; gap:8px; }}
.reasons li {{ display:flex; gap:10px; align-items:baseline; font-size:14px; }}
.pts {{ flex:none; font-size:12px; font-weight:650; color:var(--muted); background:var(--surface-2);
  border-radius:6px; padding:1px 6px; font-variant-numeric:tabular-nums; }}
.reasons li.more, .reasons li.ok {{ color:var(--muted); }}

/* snapshot tiles */
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr)); gap:16px; }}
.tile {{ padding:16px 18px; display:flex; flex-direction:column; gap:4px; }}
.tile-label {{ font-size:13px; color:var(--muted); }}
.tile-row {{ display:flex; justify-content:space-between; align-items:flex-end; gap:8px; }}
.tile-value {{ font-size:28px; font-weight:650; line-height:1.15; }}
.delta {{ font-size:13px; font-weight:600; }} .delta.up {{ color:var(--good); }} .delta.down {{ color:var(--critical); }}
.delta.flat {{ color:var(--muted); }}
.spark {{ width:120px; height:32px; }}

/* tables */
.table-wrap {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums; }}
th, td {{ padding:10px 14px; text-align:right; border-bottom:1px solid var(--line); white-space:nowrap; }}
th:first-child, td:first-child {{ text-align:left; }}
thead th {{ color:var(--muted); font-weight:600; font-size:12px; vertical-align:bottom; background:var(--surface-2); }}
thead th .th-sub {{ display:block; font-weight:400; font-size:11px; color:var(--faint); }}
tbody tr:last-child td {{ border-bottom:none; }}
tbody tr:hover td {{ background:var(--surface-2); }}
td.target, th.target {{ background:var(--accent-bg) !important; font-weight:650; }}
.mark {{ font-size:10px; margin-left:4px; }} .mark.better {{ color:var(--good); }} .mark.worse {{ color:var(--critical); }}
.dagger {{ color:var(--warning); font-weight:700; }}
.note {{ color:var(--muted); font-size:13px; margin:10px 2px 0; }}

/* charts */
.legend {{ display:flex; gap:18px; flex-wrap:wrap; font-size:14px; margin:0 0 12px; }}
.legend span {{ display:inline-flex; align-items:center; gap:8px; }}
.legend i, .tip .key {{ display:inline-block; width:16px; height:3px; border-radius:2px; }}
.charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(440px,100%),1fr)); gap:16px; }}
.chart-card {{ padding:16px 16px 8px; }}
.chart-card h3 {{ font-size:15px; margin:0; }} .chart-card p {{ margin:2px 0 6px; font-size:12px; color:var(--muted); }}
figure.chart {{ margin:0; outline:none; }}
figure.chart:focus-visible {{ box-shadow:0 0 0 2px var(--accent); border-radius:8px; }}
.plot {{ position:relative; }}
.plot svg {{ width:100%; height:auto; display:block; overflow:visible; }}
svg .grid {{ stroke:var(--grid); stroke-width:1; }} svg .zero {{ stroke:var(--faint); stroke-width:1; }}
svg .ref {{ stroke:var(--faint); stroke-dasharray:3 3; }}
svg .tick {{ fill:var(--muted); font-size:12.5px; font-variant-numeric:tabular-nums; }}
svg .end {{ fill:var(--text); font-size:13px; }} svg .endv {{ font-weight:650; }}
svg .dot {{ stroke:var(--surface); stroke-width:2; }}
svg .xh {{ stroke:var(--faint); stroke-width:1; opacity:0; pointer-events:none; }}
.tip {{ position:absolute; top:4px; min-width:170px; background:var(--surface); border:1px solid var(--line);
  border-radius:8px; padding:8px 10px; box-shadow:0 6px 20px rgba(0,0,0,.12); font-size:13px; pointer-events:none; z-index:2; }}
.tip-h {{ color:var(--muted); font-size:12px; margin-bottom:4px; }}
.tip-r {{ display:flex; align-items:center; gap:8px; margin:3px 0; }} .tip-r span:last-child {{ color:var(--muted); }}
details.data {{ margin:4px 0 4px; }} details.data summary {{ font-size:12px; color:var(--muted); cursor:pointer; }}
details.data table {{ font-size:12px; margin-top:6px; }} details.data td, details.data th {{ padding:6px 8px; }}
details.data .fy {{ display:block; color:var(--faint); font-size:10px; }}

/* notes and details */
.notes {{ display:flex; flex-direction:column; gap:10px; }}
.note-item {{ display:flex; gap:12px; padding:14px 16px; background:var(--note-bg); border-radius:10px; font-size:14px; }}
.note-item .i {{ flex:none; width:20px; height:20px; border-radius:50%; background:var(--accent); color:#fff;
  display:grid; place-items:center; font-size:12px; font-weight:700; font-style:italic; font-family:Georgia,serif; }}
.note-item details {{ display:inline; }}
.note-item details summary {{ display:inline; cursor:pointer; color:var(--link); font-size:13px; margin-left:4px; }}
.note-item details[open] {{ display:block; }}
.note-item details p {{ margin:8px 0 0; color:var(--muted); font-size:13px; }}
details.section {{ padding:0; margin-bottom:10px; }}
details.section > summary {{ cursor:pointer; font-weight:600; padding:14px 18px; list-style:none; display:flex;
  justify-content:space-between; }}
details.section > summary::after {{ content:"+"; color:var(--muted); font-weight:400; }}
details.section[open] > summary::after {{ content:"\\2212"; }}
details.section > .body {{ padding:0 18px 16px; }}
td.wrap {{ white-space:normal; text-align:left; min-width:240px; }}
footer {{ margin:48px 0 40px; color:var(--faint); font-size:12px; }}
@media (max-width:560px) {{ h1 {{ font-size:25px; }} .charts {{ grid-template-columns:1fr; }} }}
"""


def _table(head: list[str], rows: list[list[str]], head_classes: list[str] | None = None) -> str:
    head_classes = head_classes or [""] * len(head)
    ths = "".join(f'<th class="{c}">{h}</th>' if c else f"<th>{h}</th>" for h, c in zip(head, head_classes))
    body = "".join("<tr>" + "".join(row) + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div>'


def _meter(score: int, level: str) -> str:
    cells = "".join(f'<i class="{"on" if i < score else ""}"></i>' for i in range(METER_CELLS))
    return (f'<div class="meter {LEVEL_CLASS[level]}" role="img" aria-label="Score {score} of {METER_CELLS}+">'
            f'{cells}</div><div class="meter-scale"><span>Lower</span><span>Moderate</span><span>Elevated</span></div>')


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
        items = [f'<li><span class="pts" title="{escape(r.rule.id)} {escape(r.rule.name)}">+{r.points}</span>'
                 f'<span>{escape(r.detail.split(" (comparability warning")[0])}</span></li>'
                 for r in fired[:REASONS_SHOWN]]
        if len(fired) > REASONS_SHOWN:
            items.append(f'<li class="more">+{len(fired) - REASONS_SHOWN} more in the workbook</li>')
        if not fired:
            items += [f'<li class="ok">{escape(n)}</li>' for n in notes.get(name, [])[:1]] or \
                     ['<li class="ok">No warning signs triggered.</li>']
        is_target = name == result.target
        out.append(f"""
<article class="panel card{' is-target' if is_target else ''}">
  <div class="card-head">
    <div><div class="card-name">{escape(name)}{'<span class="tag">Target</span>' if is_target else ''}</div>
      <div class="period">{p.label} · year ended {long_date(p.end)}</div></div>
    <div class="score"><b>{score}</b> <span>{"pt" if score == 1 else "pts"}</span></div>
  </div>
  <span class="badge {LEVEL_CLASS[level]}"><span class="icon">{LEVEL_ICON[level]}</span>{level}</span>
  {_meter(score, level)}
  <ul class="reasons">{''.join(items)}</ul>
</article>""")
    return f'<div class="cards">{"".join(out)}</div>'


def _snapshot(result) -> str:
    year = result.latest_year
    m = result.metrics.xs(result.target, level="company")
    table = result.peer_comparison(year)
    prev_label = result.period_label(result.target, year - 1, with_date=False)
    tiles = []
    for key in SNAPSHOT_METRICS:
        metric = METRICS_BY_KEY[key]
        cur, prev = m[key].get(year), m[key].get(year - 1)
        median = table.loc[key, "Peer median (excl. target)"]
        if cur is None or cur != cur:
            continue
        delta = ""
        if prev is not None and prev == prev and not displays_equal(cur, prev, metric.fmt):
            change = cur - prev
            text = f"{change * 100:+.1f} pp" if metric.fmt == "pct" else f"{change:+.2f}x"
            good = None if metric.higher_is_better is None else (change > 0) == metric.higher_is_better
            cls = "flat" if good is None else "up" if good else "down"
            arrow = "&#9650;" if change > 0 else "&#9660;"
            delta = f'<span class="delta {cls}">{arrow} {text} vs {prev_label}</span>'
        elif prev is not None and prev == prev:
            delta = f'<span class="delta flat">unchanged vs {prev_label}</span>'
        dagger = ' <span class="dagger" title="Not directly comparable across these companies">†</span>' \
            if result.blocked(key, result.company_names) else ""
        tiles.append(f"""
<div class="panel tile">
  <div class="tile-label">{escape(metric.label)}</div>
  <div class="tile-row"><div class="tile-value">{format_value(cur, metric.fmt)}</div>{svg.sparkline(list(m[key].values))}</div>
  {delta}
  <div class="small muted">Peer median {format_value(median, metric.fmt)}{dagger}</div>
</div>""")
    return f'<div class="tiles">{"".join(tiles)}</div>'


def _periods_table(result, year: int) -> str:
    rows = []
    for name in result.company_names:
        p = result.period(name, year)
        if p:
            name_html = f"<strong>{escape(name)}</strong>" if name == result.target else escape(name)
            rows.append([f"<td>{name_html}</td>", f"<td>{p.label}</td>", f"<td>{long_date(p.end)}</td>",
                         f"<td>{year}</td>"])
    return (f'<div class="panel">{_table(["Company", "Reported fiscal year", "Period ended", "Comparison year"], rows)}'
            f'</div><p class="note">{escape(PERIOD_DISCLOSURE)}</p>')


def _chart_card(result, key: str, title: str, subtitle: str, series, fmt: str, colors, labels, **kwargs) -> str:
    dagger = (' <span class="dagger" title="Not directly comparable across these companies">†</span>'
              if key in METRICS_BY_KEY and result.blocked(key, result.company_names) else "")
    chart = svg.line_chart(f"chart-{key}", series, labels, fmt, colors, target=result.target, title=title, **kwargs)
    return (f'<div class="panel chart-card"><h3>{escape(title)}{dagger}</h3><p>{escape(subtitle)}</p>'
            f'{chart}</div>')


def _trends(result) -> tuple[str, str]:
    colors = {name: svg.series_var(i) for i, name in enumerate(result.company_names)}
    labels = {name: {y: p.label for y in result.years if (p := result.period(name, y))} for name in result.company_names}
    legend = "".join(f'<span><i style="background:var({colors[n]})"></i>{escape(n)}</span>' for n in result.company_names)

    scores = result.scores.pivot(index="comparison_year", columns="company", values="score")
    cards = [_chart_card(result, "risk_score", "Risk score", "Points from triggered rules (3+ moderate, 6+ elevated)",
                         {n: scores[n].astype(float) for n in result.company_names if n in scores}, "score", colors,
                         labels, reference_lines=((3, "Moderate"), (6, "Elevated")))]
    more = []
    for key in result.profile.metric_keys:
        metric = METRICS_BY_KEY[key]
        series = {n: result.metrics.xs(n, level="company")[key] for n in result.company_names}
        card = _chart_card(result, key, metric.label, metric.formula, series, metric.fmt, colors, labels,
                           zero_line=metric.fmt == "pct")
        (cards if key in KEY_CHARTS else more).append(card)
    main = f'<div class="legend">{legend}</div><div class="charts">{"".join(cards)}</div>'
    extra = (f'<details class="panel section"><summary>All other charts ({len(more)})</summary><div class="body">'
             f'<div class="legend">{legend}</div><div class="charts">{"".join(more)}</div></div></details>')
    return main, extra


def _peer_table(result) -> str:
    year = result.latest_year
    table = result.peer_comparison(year)
    head, classes = ["Metric"], [""]
    for c in table.columns:
        p = result.period(c, year)
        label = "Peer median" if c.startswith("Peer median") else escape(c)
        sub = f'{p.label} · {short_date(p.end)}' if p else "excl. target"
        head.append(f'{label}<span class="th-sub">{sub}</span>')
        classes.append("target" if c == result.target else "")
    rows = []
    for key, values in table.iterrows():
        metric = METRICS_BY_KEY[key]
        blocked = result.blocked(key, result.company_names)
        marker = result.peer_marker(key, year)
        dagger = ' <span class="dagger">†</span>' if blocked else ""
        cells = [f'<td title="{escape(metric.formula)}">{escape(metric.label)}{dagger}</td>']
        for col, v in values.items():
            if col == result.target:
                mark = (f'<span class="mark {marker}" aria-label="{marker} than peer median">'
                        f'{"&#9650;" if marker == "better" else "&#9660;"}</span>' if marker else "")
                cells.append(f'<td class="target">{format_value(v, metric.fmt)}{mark}</td>')
            else:
                cells.append(f"<td>{format_value(v, metric.fmt)}</td>")
        rows.append(cells)
    return (f'<div class="panel">{_table(head, rows, classes)}</div>'
            f'<p class="note"><span class="mark better">&#9650;</span> better / <span class="mark worse">&#9660;</span> '
            f'worse than the peer median · <span class="dagger">†</span> not directly comparable across these '
            f'companies (see Keep in mind) · hover a metric for its formula</p>')


def _keep_in_mind(result) -> str:
    if not result.comparability:
        return '<p class="muted">No comparability issues detected.</p>'
    items = "".join(f'<div class="note-item"><span class="i">i</span><div>{escape(w.summary or w.title)}'
                    f'<details><summary>More</summary><p>{escape(w.message)}</p></details></div></div>'
                    for w in result.comparability)
    return f'<div class="notes">{items}</div>'


def _events(result) -> str:
    if not result.events_run:
        return ""
    if result.events:
        rows = [[f"<td>{escape(e.company)}<br><span class='muted small'>{escape(e.reported_fiscal_year)}</span></td>",
                 f"<td>{escape(e.event_date)}</td>",
                 f'<td class="wrap">{escape(e.description)}<br><span class="muted small">Relates to '
                 f'{escape(e.affected_metric.lower())} · relevance {escape(e.relevance.lower())}</span></td>',
                 f'<td><a href="{escape(e.url)}" rel="noopener">{escape(e.filing_type.split(" (")[0])}</a></td>']
                for e in result.events]
        body = _table(["Company", "Date", "What the filing says", "Source"], rows)
    else:
        body = '<p class="muted">No candidate events matched the detected changes.</p>'
    return (f'<details class="panel section"><summary>Possible explanatory events from SEC filings '
            f'({len(result.events)})</summary><div class="body"><p class="note">{escape(EVENTS_DISCLAIMER)}</p>'
            f'{body}</div></details>')


def _methodology(result) -> str:
    rules = "".join(f"<tr><td>{r.id}</td><td style='text-align:left'>{escape(r.name)}</td><td>{r.points}</td>"
                    f"<td class='wrap'>{escape(r.test)}</td></tr>" for r in result.profile.rules)
    families = " · ".join(f"<strong>{p}</strong> {escape(m.replace(' rules', '').lower())}"
                          for p, m in risk.RULE_FAMILIES.items())
    data_notes = "".join(f"<li>{escape(w)}</li>" for w in result.warnings)
    return f"""
<details class="panel section"><summary>How the score works</summary><div class="body">
<p class="small">Each rule adds its points when triggered: 0-2 points = Lower Risk, 3-5 = Moderate, 6+ = Elevated.
Rules that compare against peers need at least {risk.MIN_PEERS} comparable peers to add points. The workbook's
<em>Rule Details</em> sheet shows every rule for every company and year.</p>
<p class="small muted">{families}</p>
<div class="table-wrap"><table><thead><tr><th>Rule</th><th style="text-align:left">Name</th><th>Points</th>
<th style="text-align:left">Test</th></tr></thead><tbody>{rules}</tbody></table></div></div></details>
<details class="panel section"><summary>Where the numbers come from</summary><div class="body"><ul class="small">
<li>Annual reports (10-K / 20-F) from SEC EDGAR, read from their XBRL data. Each company's own figures and
fiscal-year labels are kept; nothing is reclassified.</li>
<li>Ratios use each company's own currency. Dollar amounts use Federal Reserve exchange rates.</li>
<li>The workbook's <em>Data Lineage</em> sheet shows the exact filing and XBRL concept behind every number.</li>
{data_notes}</ul></div></details>"""


def write_summary_page(result, path: Path, chart_paths: dict[str, Path] | None, notes: dict[str, list[str]]) -> Path:
    """chart_paths is unused (the page draws its own SVG charts); kept for a stable call signature."""
    peers = ", ".join(n for n in result.company_names if n != result.target)
    year = result.latest_year
    trends, more_charts = _trends(result)
    used = sorted({form for cf in result.financials for form in cf.forms})
    forms = " and ".join(used) if len(used) <= 2 else ", ".join(used[:-1]) + " and " + used[-1]
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(result.target)} Risk Summary</title><style>{CSS}</style></head>
<body>
<header class="top"><div class="wrap">
  <div class="eyebrow">{escape(result.profile.name)} · Financial risk &amp; peer analysis</div>
  <h1>{escape(result.target)} <span class="vs">vs</span> {escape(peers)}</h1>
  <p class="lede">Comparison years {result.first_year}-{result.last_year} · risk scores for {year} ·
  built from SEC {forms} filings</p>
  <nav class="sections"><a href="#glance">At a glance</a><a href="#snapshot">{escape(result.target)} snapshot</a>
  <a href="#trends">Trends</a><a href="#peers">Peer comparison</a><a href="#notes">Keep in mind</a>
  <a href="#detail">More detail</a></nav>
</div></header>
<main class="wrap">

<section id="glance">
  <h2>Risk at a glance</h2>
  <p class="sub">Flags point to unusual financial patterns worth a closer look. They are not a finding of fraud or a
  share-price forecast.</p>
  {_cards(result, notes)}
</section>

<section id="snapshot">
  <h2>{escape(result.target)} snapshot</h2>
  <p class="sub">{escape(result.period_label(result.target, year))}, compared with the prior year and with peers.</p>
  {_snapshot(result)}
</section>

<section id="periods">
  <h2>Periods compared</h2>
  <p class="sub">Fiscal years end on different dates, so each company keeps its own label.</p>
  {_periods_table(result, year)}
</section>

<section id="trends">
  <h2>Trends</h2>
  <p class="sub">By comparison year. Hover or focus a chart to see every company's value and fiscal year.</p>
  {trends}
  <div style="margin-top:16px">{more_charts}</div>
</section>

<section id="peers">
  <h2>Peer comparison</h2>
  <p class="sub">Comparison year {year}.</p>
  {_peer_table(result)}
</section>

<section id="notes">
  <h2>Keep in mind</h2>
  <p class="sub">Differences in how the companies report that affect the comparison.</p>
  {_keep_in_mind(result)}
</section>

<section id="detail">
  <h2>More detail</h2>
  <p class="sub">The full workbook, <strong>financial_report.xlsx</strong>, is in this folder.</p>
  {_events(result)}
  {_methodology(result)}
</section>

<footer>Generated {date.today():%B} {date.today().day}, {date.today().year} from SEC EDGAR filings.
Not investment advice.</footer>
</main>
<script>{svg.CHART_SCRIPT}</script>
</body></html>"""
    path.write_text(page, encoding="utf-8")
    return path
