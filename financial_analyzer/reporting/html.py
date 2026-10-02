"""Self-contained HTML summary page (no external assets; works offline).

Layout: header, risk at a glance (one card per company with a score meter), a snapshot of
the target's key numbers, periods compared, interactive trend charts, the peer table,
comparability notes, and collapsed detail sections.
"""

from __future__ import annotations

import math
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd

from financial_analyzer.analysis import peer_check, risk
from financial_analyzer.analysis.metrics import METRICS_BY_KEY, displays_equal, format_value
from financial_analyzer.analysis.pipeline import PERIOD_DISCLOSURE
from financial_analyzer.events import DISCLAIMER as EVENTS_DISCLAIMER
from financial_analyzer.reporting import svg

KEY_CHARTS = ("operating_margin", "revenue_growth", "fcf_margin")
SNAPSHOT_METRICS = ("revenue_growth", "operating_margin", "fcf_margin", "current_ratio")
REASONS_SHOWN = 3
METER_CELLS = 10

LEVEL_CLASS = {"Lower Risk": "good", "Moderate Risk": "warning", "Elevated Risk": "critical"}
LEVEL_ICON = {"Lower Risk": "&#10003;", "Moderate Risk": "!", "Elevated Risk": "&#9888;"}

_SERIES_LIGHT = ["#0b7fd6", "#e8590c", "#0f9f6e", "#c98a00", "#d6336c", "#2f9e44", "#6741d9", "#e03131"]
_SERIES_DARK = ["#38bdf8", "#fb923c", "#34d399", "#facc15", "#f472b6", "#4ade80", "#a78bfa", "#f87171"]


def _vars(values: list[str]) -> str:
    return " ".join(f"--s{i}:{v};" for i, v in enumerate(values, 1))


# Dark is the default look; the toggle in the nav bar switches to light (remembered per browser).
_LIGHT = f"""--bg:#f3f5f8; --surface:#ffffff; --surface-2:#f0f3f7; --text:#0d1420; --muted:#526074; --faint:#8593a6;
  --line:#dde3ea; --grid:#e9edf2; --track:#e3e8ee; --accent:#0891b2; --accent-2:#7c3aed; --accent-bg:#e0f6fb;
  --link:#0e7490; --glow:rgba(8,145,178,.18); --good:#0f9f6e; --warning:#c98a00; --critical:#dc2626;
  --good-bg:#dcf5eb; --warning-bg:#fdf1d3; --critical-bg:#fde2e2; --note-bg:#f5f8fc; --shadow:rgba(15,23,42,.10);
  {_vars(_SERIES_LIGHT)} color-scheme:light;"""

MONO = 'ui-monospace,"Cascadia Code","JetBrains Mono","SF Mono",SFMono-Regular,Menlo,Consolas,monospace'

CSS = f"""
:root {{ --bg:#070b12; --surface:#0d131d; --surface-2:#121a27; --text:#e6edf6; --muted:#8d9bb0; --faint:#5d6b80;
  --line:#1c2635; --grid:#151e2c; --track:#1c2635; --accent:#22d3ee; --accent-2:#a78bfa; --accent-bg:rgba(34,211,238,.1);
  --link:#67e8f9; --glow:rgba(34,211,238,.35); --good:#34d399; --warning:#fbbf24; --critical:#f87171;
  --good-bg:rgba(52,211,153,.12); --warning-bg:rgba(251,191,36,.12); --critical-bg:rgba(248,113,113,.13);
  --note-bg:#0f1826; --shadow:rgba(0,0,0,.35); {_vars(_SERIES_DARK)} color-scheme:dark; }}
:root[data-theme="light"] {{ {_LIGHT} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
  font:15px/1.55 "Inter","Segoe UI Variable","Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
  -webkit-font-smoothing:antialiased; }}
a {{ color:var(--link); }}
::selection {{ background:var(--accent); color:#001018; }}
.wrap {{ max-width:1120px; margin:0 auto; padding:0 20px; }}

/* header: always dark, blueprint grid + glow */
header.top {{ --hdr-line:rgba(148,163,184,.05); background-color:#05080e; color:#e6edf6; padding:40px 0 34px;
  position:relative; overflow:hidden; border-bottom:1px solid #1c2635;
  background-image:radial-gradient(ellipse 55% 90% at 90% 0%,rgba(34,211,238,.10),transparent 60%),
    linear-gradient(var(--hdr-line) 1px,transparent 1px),linear-gradient(90deg,var(--hdr-line) 1px,transparent 1px);
  background-size:auto,32px 32px,32px 32px; }}
.hero {{ display:flex; justify-content:space-between; align-items:center; gap:28px; flex-wrap:wrap; position:relative; z-index:1; }}
.eyebrow {{ font:600 12px/1 {MONO}; letter-spacing:.14em; text-transform:uppercase; color:#7dd3e8; }}
h1 {{ font-size:52px; line-height:1.05; margin:14px 0 14px; letter-spacing:-.03em; font-weight:700;
  display:flex; align-items:center; gap:16px; flex-wrap:wrap; }}
.ticker {{ font:600 14px/1 {MONO}; letter-spacing:.08em; padding:7px 11px; border-radius:6px; color:#b6c4d6;
  background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.14); }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; margin:0; padding:0; list-style:none; }}
.chips li {{ font:12px/1 {MONO}; color:#b6c4d6; padding:7px 10px; border-radius:6px; background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.09); }}
.chips li b {{ color:#6b7c93; font-weight:500; margin-right:6px; text-transform:uppercase; letter-spacing:.08em; }}
.verdict {{ display:flex; align-items:center; gap:18px; padding:18px 22px; border-radius:14px; min-width:300px;
  background:rgba(13,19,29,.85); border:1px solid #223047; }}
.gauge {{ width:108px; height:108px; flex:none; }}
.gauge .trk {{ stroke:#1a2536; }}
.gauge text {{ font-family:{MONO}; fill:#e6edf6; }}
.gauge .unit {{ fill:#6b7c93; }}
.gauge.good .val {{ stroke:#34d399; }}
.gauge.warning .val {{ stroke:#fbbf24; }}
.gauge.critical .val {{ stroke:#f87171; }}
.verdict-label {{ font:600 11px/1 {MONO}; color:#6b7c93; text-transform:uppercase; letter-spacing:.14em; }}
.verdict-level {{ font-size:22px; font-weight:700; margin:8px 0 6px; letter-spacing:-.01em; }}
.verdict-level.good {{ color:#34d399; }} .verdict-level.warning {{ color:#fbbf24; }} .verdict-level.critical {{ color:#f87171; }}
.verdict-period {{ font:12px/1.4 {MONO}; color:#8d9bb0; }}

/* sticky nav */
nav.sections {{ position:sticky; top:0; z-index:5; background:color-mix(in srgb, var(--bg) 82%, transparent);
  backdrop-filter:blur(12px) saturate(140%); border-bottom:1px solid var(--line); }}
nav.sections .wrap {{ display:flex; align-items:center; gap:2px; overflow-x:auto; }}
nav.sections a {{ color:var(--muted); text-decoration:none; font:13px/1 {MONO}; padding:15px 12px 13px; white-space:nowrap;
  border-bottom:2px solid transparent; transition:color .15s, border-color .15s; }}
nav.sections a:hover {{ color:var(--text); border-bottom-color:var(--accent); }}
nav.sections a span {{ color:var(--accent); opacity:.7; margin-right:6px; }}
.theme-btn {{ margin-left:auto; flex:none; font:12px/1 {MONO}; color:var(--muted); background:var(--surface);
  border:1px solid var(--line); border-radius:6px; padding:7px 10px; cursor:pointer; }}
.theme-btn:hover {{ color:var(--text); border-color:var(--accent); }}

/* sections */
section {{ margin:56px 0 0; scroll-margin-top:60px; }}
.section-head {{ display:flex; align-items:center; gap:14px; margin:0 0 6px; }}
.section-num {{ font:700 12px/1 {MONO}; color:var(--accent); letter-spacing:.08em; padding:5px 7px; border-radius:5px;
  background:var(--accent-bg); border:1px solid color-mix(in srgb, var(--accent) 35%, transparent); }}
h2 {{ font-size:24px; margin:0; letter-spacing:-.02em; font-weight:700; }}
.section-head::after {{ content:""; flex:1; height:1px; background:linear-gradient(90deg,var(--line),transparent); }}
.sub {{ color:var(--muted); font-size:14px; margin:0 0 20px; }}
.muted {{ color:var(--muted); }} .small {{ font-size:13px; }}
.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:12px;
  box-shadow:0 10px 30px -18px var(--shadow); }}
.card, .tile {{ transition:border-color .15s ease; }}
.card:hover, .tile:hover {{ border-color:color-mix(in srgb, var(--accent) 30%, var(--line)); }}

/* risk cards */
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(310px,100%),1fr)); gap:16px; }}
.card {{ padding:20px; display:flex; flex-direction:column; gap:12px; }}
.card.is-target {{ border-color:color-mix(in srgb, var(--accent) 70%, var(--line));
  background:linear-gradient(180deg,color-mix(in srgb, var(--accent) 9%, var(--surface)),var(--surface) 70%);
  box-shadow:inset 0 3px 0 var(--accent),0 10px 30px -18px var(--shadow); }}
.card.is-target:hover {{ border-color:var(--accent); }}
.card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }}
.card-name {{ font-size:19px; font-weight:700; letter-spacing:-.01em; }}
.tag {{ font:600 10px/1 {MONO}; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); background:var(--accent-bg);
  border:1px solid color-mix(in srgb, var(--accent) 40%, transparent); border-radius:4px; padding:3px 6px; margin-left:8px; vertical-align:3px; }}
.period {{ font:12px/1.5 {MONO}; color:var(--muted); margin-top:2px; }}
.score {{ text-align:right; line-height:1; font-family:{MONO}; }}
.score b {{ font-size:34px; font-weight:700; }} .score span {{ font-size:12px; color:var(--muted); }}
.badge {{ align-self:flex-start; display:inline-flex; align-items:center; gap:6px; padding:3px 10px 3px 4px;
  border-radius:999px; font-size:12px; font-weight:650; letter-spacing:.01em; }}
.badge .icon {{ display:inline-grid; place-items:center; width:18px; height:18px; border-radius:50%; color:#04121a; font-size:11px; font-weight:800; }}
.badge.good {{ background:var(--good-bg); color:var(--good); }} .badge.good .icon {{ background:var(--good); }}
.badge.warning {{ background:var(--warning-bg); color:var(--warning); }} .badge.warning .icon {{ background:var(--warning); }}
.badge.critical {{ background:var(--critical-bg); color:var(--critical); }} .badge.critical .icon {{ background:var(--critical); color:#fff; }}
.meter {{ display:grid; grid-template-columns:repeat({METER_CELLS},1fr); gap:4px; }}
.meter i {{ height:8px; border-radius:2px; background:var(--track); }}
.meter.good i.on {{ background:var(--good); }}
.meter.warning i.on {{ background:var(--warning); }}
.meter.critical i.on {{ background:var(--critical); }}
.meter-scale {{ display:grid; grid-template-columns:3fr 3fr 4fr; font:10px/1 {MONO}; letter-spacing:.08em;
  text-transform:uppercase; color:var(--faint); margin-top:-4px; }}
.reasons {{ list-style:none; margin:4px 0 0; padding:12px 0 0; display:flex; flex-direction:column; gap:9px;
  border-top:1px dashed var(--line); }}
.reasons li {{ display:flex; gap:10px; align-items:baseline; font-size:14px; }}
.pts {{ flex:none; font:700 11px/1.6 {MONO}; color:var(--accent); background:var(--accent-bg);
  border-radius:4px; padding:0 6px; }}
.reasons li.more, .reasons li.ok {{ color:var(--muted); }}

/* snapshot tiles */
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(230px,100%),1fr)); gap:16px; }}
.tile {{ padding:16px 18px; display:flex; flex-direction:column; gap:6px; }}
.tile-label {{ font:600 11px/1.3 {MONO}; letter-spacing:.1em; text-transform:uppercase; color:var(--muted); }}
.tile-row {{ display:flex; justify-content:space-between; align-items:flex-end; gap:8px; }}
.tile-value {{ font:700 30px/1.1 {MONO}; letter-spacing:-.02em; }}
.delta {{ font:600 12px/1.4 {MONO}; }} .delta.up {{ color:var(--good); }} .delta.down {{ color:var(--critical); }}
.delta.flat {{ color:var(--muted); }}
.tile .small {{ font-family:{MONO}; font-size:12px; }}
.spark {{ width:120px; height:34px; overflow:visible; }}
.spark path {{ stroke:var(--accent); opacity:.85; }} .spark circle {{ fill:var(--accent); }}

/* tables */
.table-wrap {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums; }}
th, td {{ padding:11px 14px; text-align:right; border-bottom:1px solid var(--line); white-space:nowrap; }}
td {{ font-family:{MONO}; font-size:13px; }}
td:first-child {{ font-family:inherit; font-size:14px; }}
th:first-child, td:first-child {{ text-align:left; }}
thead th {{ color:var(--muted); font:600 11px/1.3 {MONO}; letter-spacing:.08em; text-transform:uppercase;
  vertical-align:bottom; background:var(--surface-2); }}
thead th:first-child {{ border-top-left-radius:11px; }} thead th:last-child {{ border-top-right-radius:11px; }}
thead th .co {{ font:650 13px/1.3 "Inter","Segoe UI Variable","Segoe UI",system-ui,sans-serif;
  text-transform:none; letter-spacing:0; color:var(--text); }}
thead th.target .co {{ color:var(--accent); }}
thead th .th-sub {{ display:block; font-weight:400; font-size:10px; color:var(--faint); text-transform:none; letter-spacing:0; }}
tbody tr:last-child td {{ border-bottom:none; }}
tbody tr:hover td {{ background:color-mix(in srgb, var(--accent) 5%, var(--surface)); }}
td.target, th.target {{ background:var(--accent-bg) !important; color:var(--text); font-weight:700; }}
th.target {{ color:var(--accent); }}
.mark {{ font-size:10px; margin-left:5px; }} .mark.better {{ color:var(--good); }} .mark.worse {{ color:var(--critical); }}
.dagger {{ color:var(--warning); font-weight:700; }}
.nm {{ color:var(--faint); cursor:help; }}
.note {{ color:var(--muted); font-size:13px; margin:12px 2px 0; }}

/* charts */
.legend {{ display:flex; gap:18px; flex-wrap:wrap; font:13px/1 {MONO}; margin:0 0 14px; color:var(--muted); }}
.legend span {{ display:inline-flex; align-items:center; gap:8px; }}
.legend i, .tip .key {{ display:inline-block; width:16px; height:3px; border-radius:2px; }}
.charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(460px,100%),1fr)); gap:16px; }}
.chart-card {{ padding:18px 18px 10px; }}
.chart-card h3 {{ font-size:15px; margin:0; font-weight:700; }}
.chart-card p {{ margin:3px 0 8px; font:11px/1.4 {MONO}; color:var(--faint); }}
figure.chart {{ margin:0; outline:none; }}
figure.chart:focus-visible {{ box-shadow:0 0 0 2px var(--accent); border-radius:8px; }}
.plot {{ position:relative; }}
.plot svg {{ width:100%; height:auto; display:block; overflow:visible; }}
svg .grid {{ stroke:var(--grid); stroke-width:1; }} svg .zero {{ stroke:var(--faint); stroke-width:1; }}
svg .ref {{ stroke:var(--warning); stroke-dasharray:4 4; opacity:.6; }}
svg .tick {{ fill:var(--faint); font-size:11.5px; font-family:{MONO}; font-variant-numeric:tabular-nums; }}
svg .end {{ fill:var(--text); font-size:12.5px; }} svg .endv {{ font-weight:700; font-family:{MONO}; }}
svg .dot {{ stroke:var(--surface); stroke-width:2; }}
svg .xh {{ stroke:var(--accent); stroke-width:1; stroke-dasharray:2 3; opacity:0; pointer-events:none; }}
.tip {{ position:absolute; top:4px; min-width:180px; background:color-mix(in srgb, var(--surface) 92%, transparent);
  backdrop-filter:blur(8px); border:1px solid var(--line);
  border-radius:8px; padding:9px 11px; box-shadow:0 12px 30px -8px var(--shadow);
  font:12px/1.4 {MONO}; pointer-events:none; z-index:2; }}
.tip-h {{ color:var(--accent); font-size:11px; margin-bottom:5px; text-transform:uppercase; letter-spacing:.08em; }}
.tip-r {{ display:flex; align-items:center; gap:8px; margin:3px 0; }} .tip-r span:last-child {{ color:var(--muted); }}
details.data {{ margin:6px 0 4px; }} details.data summary {{ font:11px/1 {MONO}; color:var(--faint); cursor:pointer; }}
details.data summary:hover {{ color:var(--accent); }}
details.data table {{ font-size:12px; margin-top:6px; }} details.data td, details.data th {{ padding:6px 8px; }}
details.data .fy {{ display:block; color:var(--faint); font-size:10px; }}

/* notes and details */
.notes {{ display:flex; flex-direction:column; gap:10px; }}
.note-item {{ display:flex; gap:12px; padding:14px 16px; background:var(--note-bg); border-radius:10px; font-size:14px;
  border:1px solid var(--line); border-left:3px solid var(--accent); }}
.note-item.caution {{ border-left-color:var(--warning); background:var(--warning-bg); }}
.note-item.caution .i {{ background:var(--warning); color:#04121a; }}
.note-item .i {{ flex:none; width:20px; height:20px; border-radius:5px; background:var(--accent-bg);
  color:var(--accent); display:grid; place-items:center; font:700 12px/1 {MONO}; }}
.note-item details {{ display:inline; }}
.note-item details summary {{ display:inline; cursor:pointer; color:var(--link); font:12px/1 {MONO}; margin-left:6px; }}
.note-item details[open] {{ display:block; }}
.note-item details p {{ margin:8px 0 0; color:var(--muted); font-size:13px; }}
details.section {{ padding:0; margin-bottom:10px; }}
details.section > summary {{ cursor:pointer; font-weight:650; padding:15px 18px; list-style:none; display:flex;
  justify-content:space-between; align-items:center; }}
details.section > summary::-webkit-details-marker {{ display:none; }}
details.section > summary::after {{ content:"+"; color:var(--muted); font:400 18px/1 {MONO}; }}
details.section[open] > summary::after {{ content:"\\2212"; }}
details.section > summary:hover::after {{ color:var(--accent); }}
details.section > .body {{ padding:0 18px 16px; }}
th.left, td.left {{ text-align:left; }}
td.left {{ font-family:inherit; font-size:14px; }}
td .th-sub {{ display:block; font:11px/1.4 {MONO}; color:var(--faint); font-weight:400; }}
.small-badge {{ font-size:11px; padding:2px 8px 2px 3px; }} .small-badge .icon {{ width:16px; height:16px; font-size:10px; }}
td.wrap {{ white-space:normal; text-align:left; min-width:240px; font-family:inherit; font-size:14px; }}
td.industry {{ white-space:normal; min-width:220px; }}
footer {{ margin:64px 0 40px; padding-top:18px; border-top:1px solid var(--line); color:var(--faint);
  font:12px/1.6 {MONO}; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
@media (max-width:640px) {{ h1 {{ font-size:36px; }} .verdict {{ width:100%; min-width:0; }} .charts {{ grid-template-columns:1fr; }} }}
@media (prefers-reduced-motion:reduce) {{ *, *::before, *::after {{ animation:none !important; transition:none !important; }}
  .card:hover, .tile:hover {{ transform:none; }} }}
"""

THEME_SCRIPT = """
(function () {
  var root = document.documentElement, btn = document.querySelector('.theme-btn');
  function label() { btn.textContent = root.dataset.theme === 'light' ? 'Dark mode' : 'Light mode'; }
  label();
  btn.addEventListener('click', function () {
    if (root.dataset.theme === 'light') delete root.dataset.theme; else root.dataset.theme = 'light';
    try { localStorage.setItem('fa-theme', root.dataset.theme || 'dark'); } catch (e) {}
    label();
  });
})();
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


def _financial_banner(result) -> str:
    """A prominent caution when the comparison includes banks or insurers (see peer_check.FINANCIAL_WARNING)."""
    if not (result.peer_fit and result.peer_fit.financial_companies):
        return ""
    note = next(n for n in result.peer_fit.notes if "financial company" in n)
    return (f'<div class="note-item caution" style="margin-bottom:16px"><span class="i">!</span>'
            f'<div>{escape(note)}</div></div>')


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
<article class="panel card {LEVEL_CLASS[level]}{' is-target' if is_target else ''}">
  <div class="card-head">
    <div><div class="card-name">{escape(name)}{'<span class="tag">Target</span>' if is_target else ''}</div>
      <div class="period">{p.summary}</div></div>
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


_FIT_BADGES = {
    peer_check.SAME: ("good", "&#10003;", "Same industry"),
    peer_check.RELATED: ("good", "&#10003;", "Related industry"),
    peer_check.SECTOR: ("warning", "!", "Different industry"),
    peer_check.DIFFERENT: ("critical", "&#9888;", "Different sector"),
    peer_check.UNKNOWN: ("warning", "?", "Industry unknown"),
}


SIZE_ITEMS = (("revenue", "Revenue"), ("net_income", "Net income"), ("total_assets", "Total assets"))


def _companies_table(result, year: int) -> str:
    """Who is compared: SEC industry, how well each peer fits, each company's own period and its size."""
    values = {cf.company.name: cf.values.get(year, {}) for cf in result.financials}
    fit = result.peer_fit
    fits = {f.profile.company.name: f for f in (fit.peers if fit else [])}
    rows = []
    for name in result.company_names:
        p = result.period(name, year)
        if not p:
            continue
        if name == result.target:
            industry = fit.target if fit else None
            badge = '<span class="tag">Target</span>'
            name_html = f"<strong>{escape(name)}</strong>"
        else:
            industry = fits[name].profile if name in fits else None
            cls, icon, text = _FIT_BADGES[fits[name].match] if name in fits else _FIT_BADGES[peer_check.UNKNOWN]
            badge = f'<span class="badge small-badge {cls}"><span class="icon">{icon}</span>{text}</span>'
            name_html = escape(name)
        sic = (f'{escape(industry.industry)}<span class="th-sub">SIC {industry.sic}</span>'
               if industry and industry.sic else "Unknown")
        size = [f"<td>{format_value(v.usd if (v := values.get(name, {}).get(key)) else None, 'usd')}</td>"
                for key, _ in SIZE_ITEMS]
        rows.append([f"<td>{name_html}</td>", f'<td class="left industry">{sic}</td>', f'<td class="left">{badge}</td>',
                     f'<td>{p.months}<span class="th-sub">{p.own_label}</span></td>', *size])
    head = ["Company", "SEC industry", "Peer fit", f'Year<span class="th-sub">{year}</span>',
            *(f'{label}<span class="th-sub">USD</span>' for _, label in SIZE_ITEMS)]
    notes = [n for n in (fit.notes if fit else [])
             if not n.startswith("Fiscal years end") and "financial company" not in n]  # banner shows that one
    note_html = "".join(f'<div class="note-item"><span class="i">i</span><div>{escape(n)}</div></div>' for n in notes)
    return (f'<div class="panel">{_table(head, rows, ["", "left", "left", "", "", "", ""])}</div>'
            f'<p class="note">{escape(PERIOD_DISCLOSURE)}</p>'
            + (f'<div class="notes" style="margin-top:12px">{note_html}</div>' if note_html else ""))


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
    # Size in dollars, so a margin can be read against how big each company is.
    for key, title in (("revenue", "Revenue (USD)"), ("net_income", "Net income (USD)")):
        series = {cf.company.name: pd.Series({y: v[key].usd for y, v in cf.values.items()
                                              if y in result.years and key in v and v[key].usd is not None},
                                             dtype=float)
                  for cf in result.financials}
        cards.append(_chart_card(result, key, title, "Reported in each company's currency, converted at average "
                                 "Federal Reserve exchange rates", series, "usd", colors, labels,
                                 zero_line=key == "net_income"))
    more = []
    for key in result.profile.metric_keys:
        metric = METRICS_BY_KEY[key]
        series = {n: result.metrics.xs(n, level="company")[key] for n in result.company_names}
        blanks = {n: {y: r for y in result.years if (r := _blank_reason(result, n, key, y))}
                  for n in result.company_names}
        card = _chart_card(result, key, metric.label, metric.formula, series, metric.fmt, colors, labels,
                           zero_line=metric.fmt == "pct", blanks=blanks)
        (cards if key in KEY_CHARTS else more).append(card)
    main = f'<div class="legend">{legend}</div><div class="charts">{"".join(cards)}</div>'
    extra = (f'<details class="panel section"><summary>All other charts ({len(more)})</summary><div class="body">'
             f'<div class="legend">{legend}</div><div class="charts">{"".join(more)}</div></div></details>')
    return main, extra


NET_LOSS_BLANK = "n/m (net loss)"


NO_CAPEX_BLANK = "n/a (no PP&E capex)"
NOT_REPORTED_BLANK = "n/a (not reported)"
_CAPEX_METRICS = ("fcf_margin", "capex_pct_revenue", "capex_growth")
# Line items a metric needs, for explaining a blank: the company doesn't report that line.
_METRIC_INPUTS = {"gross_margin": ("gross_profit",), "operating_margin": ("operating_income",),
                  "inventory_growth": ("inventory",), "inventory_turnover": ("inventory", "cost_of_revenue"),
                  "days_inventory": ("inventory", "cost_of_revenue")}
_BLANK_TITLES = {NET_LOSS_BLANK: "Not meaningful: the company reported a net loss",
                 NO_CAPEX_BLANK: "The company does not report cash paid for property, plant and equipment separately",
                 NOT_REPORTED_BLANK: "The company's financial statements do not include this line"}


def _blank_reason(result, company: str, key: str, year: int) -> str | None:
    """Why a value is missing, when the reason is known: a ratio over net income is meaningless for a net loss,
    and capex-based ratios need a PP&E capex figure the company may not report separately."""
    if company not in result.company_names:
        return None
    if key == "ocf_to_net_income":
        ni = result.metrics.xs(company, level="company")["_net_income"].get(year)
        return NET_LOSS_BLANK if ni is not None and ni < 0 else None
    cf = next(cf for cf in result.financials if cf.company.name == company)
    row = cf.values.get(year)
    if row is None:
        return None
    if key in _CAPEX_METRICS and "capex" not in row:
        return NO_CAPEX_BLANK
    if any(item not in row for item in _METRIC_INPUTS.get(key, ())):
        return NOT_REPORTED_BLANK
    return None


def _cell_value(result, company: str, key: str, year: int, value: float, fmt: str) -> str:
    """Formatted value; a value left blank for a known reason says why instead of a bare n/a."""
    if value == value or not (reason := _blank_reason(result, company, key, year)):
        return format_value(value, fmt)
    return f'<span class="nm" title="{_BLANK_TITLES[reason]}">{escape(reason)}</span>'


def _peer_table(result) -> str:
    year = result.latest_year
    table = result.peer_comparison(year)
    head, classes = [f'Metric<span class="th-sub">{year}</span>'], [""]
    for c in table.columns:
        p = result.period(c, year)
        label = f'<span class="co">{"Peer median" if c.startswith("Peer median") else escape(c)}</span>'
        sub = (p.months + (f"<br>{p.own_label}" if p.own_label else "")) if p else "excl. target"
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
                cells.append(f'<td class="target">{_cell_value(result, col, key, year, v, metric.fmt)}{mark}</td>')
            else:
                cells.append(f"<td>{_cell_value(result, col, key, year, v, metric.fmt)}</td>")
        rows.append(cells)
    return (f'<div class="panel">{_table(head, rows, classes)}</div>'
            f'<p class="note"><span class="mark better">&#9650;</span> better / <span class="mark worse">&#9660;</span> '
            f'worse than the peer median · <span class="dagger">†</span> not directly comparable across these '
            f'companies (see Keep in mind) · hover a metric for its formula</p>')


def _industry_notes(result) -> list[str]:
    """The industry profile's notes that apply here: general ones, and ones naming a company in this comparison."""
    known = {n.split()[0] for n in result.profile.suggested_companies}
    present = {n.split()[0] for n in result.company_names}
    return [note for note in result.profile.notes
            if present & set(note.replace(",", " ").replace("'s", " ").split()) or
            not known & set(note.replace(",", " ").replace("'s", " ").split())]


def _keep_in_mind(result) -> str:
    items = "".join(f'<div class="note-item"><span class="i">i</span><div>{escape(w.summary or w.title)}'
                    f'<details><summary>More</summary><p>{escape(w.message)}</p></details></div></div>'
                    for w in result.comparability)
    items += "".join(f'<div class="note-item"><span class="i">i</span><div>{escape(note)}</div></div>'
                     for note in _industry_notes(result))
    if not items:
        return '<p class="muted">No comparability issues detected.</p>'
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


def _section(number: int, sid: str, title: str, subtitle: str, body: str) -> str:
    return (f'<section id="{sid}"><div class="section-head"><span class="section-num">{number:02d}</span>'
            f'<h2>{title}</h2></div><p class="sub">{subtitle}</p>{body}</section>')


def _verdict(result) -> str:
    """The target's risk score and level, shown in the page header."""
    year = result.latest_year
    row = result.scores[(result.scores.company == result.target) & (result.scores.comparison_year == year)]
    if row.empty:
        return ""
    score, level = int(row.iloc[0]["score"]), row.iloc[0]["risk_level"]
    p = result.period(result.target, year)
    r, cls = 44, LEVEL_CLASS[level]
    circ = 2 * math.pi * r
    filled = circ * min(score, METER_CELLS) / METER_CELLS
    gauge = (f'<svg class="gauge {cls}" viewBox="0 0 108 108" role="img" aria-label="Score {score} of {METER_CELLS}+">'
             f'<circle class="trk" cx="54" cy="54" r="{r}" fill="none" stroke-width="8"/>'
             f'<circle class="val" cx="54" cy="54" r="{r}" fill="none" stroke-width="8" stroke-linecap="round" '
             f'stroke-dasharray="{filled:.1f} {circ:.1f}" transform="rotate(-90 54 54)"/>'
             f'<text x="54" y="58" text-anchor="middle" font-size="30" font-weight="700">{score}</text>'
             f'<text class="unit" x="54" y="76" text-anchor="middle" font-size="10">/ {METER_CELLS} PTS</text></svg>')
    return (f'<div class="verdict">{gauge}<div><div class="verdict-label">Risk score</div>'
            f'<div class="verdict-level {cls}">{level}</div>'
            f'<div class="verdict-period">{p.summary}</div></div></div>')


def write_summary_page(result, path: Path, chart_paths: dict[str, Path] | None, notes: dict[str, list[str]]) -> Path:
    """chart_paths is unused (the page draws its own SVG charts); kept for a stable call signature."""
    peer_names = [n for n in result.company_names if n != result.target]
    peers = peer_names[0] if len(peer_names) == 1 else ", ".join(peer_names[:-1]) + " and " + peer_names[-1]
    target_co = next(cf.company for cf in result.financials if cf.company.name == result.target)
    year = result.latest_year
    trends, more_charts = _trends(result)
    nav = "".join(f'<a href="#{sid}"><span>{i:02d}</span>{escape(label)}</a>' for i, (sid, label) in enumerate(
        [("glance", "At a glance"), ("snapshot", f"{result.target} snapshot"), ("companies", "Companies"),
         ("trends", "Trends"), ("peers", "Peers"), ("notes", "Keep in mind"), ("detail", "More detail")], 1))
    used = sorted({form for cf in result.financials for form in cf.forms})
    forms = " and ".join(used) if len(used) <= 2 else ", ".join(used[:-1]) + " and " + used[-1]
    # "Other" says nothing useful in the header; show the target's SEC industry instead when known.
    industry = result.profile.name
    if industry == "Other":
        sec = result.peer_fit.target if result.peer_fit else None
        industry = sec.industry if sec else ""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(result.target)} Risk Summary</title><style>{CSS}</style>
<script>try {{ if (localStorage.getItem('fa-theme') === 'light') document.documentElement.dataset.theme = 'light'; }} catch (e) {{}}</script>
</head>
<body>
<header class="top"><div class="wrap hero">
  <div>
    <div class="eyebrow">{escape(industry + " · " if industry else "")}Financial risk report</div>
    <h1>{escape(result.target)} <span class="ticker">{escape(target_co.ticker)}</span></h1>
    <ul class="chips"><li><b>vs</b>{escape(peers)}</li><li><b>years</b>{result.first_year}-{result.last_year}</li>
      <li><b>source</b>SEC {forms}</li></ul>
  </div>
  {_verdict(result)}
</div></header>
<nav class="sections" aria-label="Sections"><div class="wrap">{nav}<button class="theme-btn" type="button">Light mode</button></div></nav>
<main class="wrap">
{_section(1, "glance", "Risk at a glance", "Flags point to unusual financial patterns worth a closer look. They are "
          "not a finding of fraud or a share-price forecast. Many rules compare each company with the others here, "
          "so a different peer group can change the scores.", _financial_banner(result) + _cards(result, notes))}
{_section(2, "snapshot", f"{escape(result.target)} snapshot",
          f"{escape(result.period_label(result.target, year))}, compared with the prior year and with peers.",
          _snapshot(result))}
{_section(3, "companies", "Companies compared", "Peers are checked against the SEC's industry classification. "
          "Fiscal years end on different dates, so each company keeps its own label.", _companies_table(result, year))}
{_section(4, "trends", "Trends", "By comparison year. Hover or focus a chart to see every company's value and fiscal "
          "year.", trends + f'<div style="margin-top:16px">{more_charts}</div>')}
{_section(5, "peers", "Peer comparison", f"Comparison year {year}.", _peer_table(result))}
{_section(6, "notes", "Keep in mind", "Differences in how the companies report that affect the comparison.",
          _keep_in_mind(result))}
{_section(7, "detail", "More detail", "The full workbook, <strong>financial_report.xlsx</strong>, is in this folder.",
          _events(result) + _methodology(result))}

<footer><span>Generated {date.today():%B} {date.today().day}, {date.today().year} from SEC EDGAR filings</span><span>Not investment advice.</span></footer>
</main>
<script>{svg.CHART_SCRIPT}{THEME_SCRIPT}</script>
</body></html>"""
    path.write_text(page, encoding="utf-8")
    return path
