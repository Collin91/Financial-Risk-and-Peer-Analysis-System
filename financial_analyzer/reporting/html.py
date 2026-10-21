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

_SERIES_LIGHT = ["#1d4ed8", "#c2410c", "#047857", "#a16207", "#be185d", "#4d7c0f", "#6d28d9", "#b91c1c"]
_SERIES_DARK = ["#60a5fa", "#fb923c", "#34d399", "#facc15", "#f472b6", "#a3e635", "#a78bfa", "#f87171"]


def _vars(values: list[str]) -> str:
    return " ".join(f"--s{i}:{v};" for i, v in enumerate(values, 1))


# Dark is the default look; the toggle in the nav bar switches to light (remembered per browser).
_LIGHT = f"""--bg:#f5f6f8; --surface:#ffffff; --surface-2:#f7f8fa; --text:#111827; --muted:#4b5563; --faint:#8a94a3;
  --line:#e3e6eb; --grid:#eef0f3; --track:#e5e8ec; --accent:#1d4ed8; --accent-bg:#eef3fe; --link:#1d4ed8;
  --good:#15803d; --warning:#b45309; --critical:#b91c1c; --good-bg:#e8f5ec; --warning-bg:#fdf3e2;
  --critical-bg:#fcebeb; --note-bg:#f8f9fb; --shadow:rgba(17,24,39,.06); --on-status:#ffffff;
  {_vars(_SERIES_LIGHT)} color-scheme:light;"""

SANS = '"Inter","Segoe UI Variable","Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif'

CSS = f"""
:root {{ --bg:#0e131a; --surface:#151b24; --surface-2:#1a212c; --text:#e6e9ee; --muted:#9aa4b2; --faint:#6b7585;
  --line:#252d39; --grid:#1d2430; --track:#252d39; --accent:#60a5fa; --accent-bg:rgba(96,165,250,.10); --link:#93c5fd;
  --good:#4ade80; --warning:#f5b740; --critical:#f87171; --good-bg:rgba(74,222,128,.10);
  --warning-bg:rgba(245,183,64,.11); --critical-bg:rgba(248,113,113,.11); --note-bg:#171e28;
  --shadow:rgba(0,0,0,.25); --on-status:#0e131a; {_vars(_SERIES_DARK)} color-scheme:dark; }}
:root[data-theme="light"] {{ {_LIGHT} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.55 {SANS};
  font-variant-numeric:tabular-nums; -webkit-font-smoothing:antialiased; }}
a {{ color:var(--link); }}
::selection {{ background:var(--accent); color:#fff; }}
.wrap {{ max-width:1120px; margin:0 auto; padding:0 24px; }}

/* header: always navy */
header.top {{ background:#0f1e36; color:#f1f4f8; padding:36px 0 32px; border-bottom:1px solid #1f3254; }}
.hero {{ display:flex; justify-content:space-between; align-items:center; gap:28px; flex-wrap:wrap; }}
.eyebrow {{ font-size:12px; font-weight:600; letter-spacing:.09em; text-transform:uppercase; color:#93a8c6; }}
h1 {{ font-size:40px; line-height:1.1; margin:10px 0 14px; letter-spacing:-.02em; font-weight:650;
  display:flex; align-items:center; gap:14px; flex-wrap:wrap; }}
.ticker {{ font-size:13px; font-weight:600; letter-spacing:.06em; padding:5px 9px; border-radius:4px; color:#c9d5e6;
  border:1px solid rgba(255,255,255,.22); }}
.chips {{ display:flex; flex-wrap:wrap; gap:6px 22px; margin:0; padding:0; list-style:none; }}
.chips li {{ font-size:13.5px; color:#dbe3ee; }}
.chips li b {{ color:#8197b6; font-weight:600; margin-right:7px; text-transform:uppercase; font-size:11px; letter-spacing:.08em; }}
.verdict {{ display:flex; align-items:center; gap:18px; padding:16px 22px; border-radius:8px; min-width:300px;
  background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.12); }}
.gauge {{ width:96px; height:96px; flex:none; }}
.gauge .trk {{ stroke:rgba(255,255,255,.12); }}
.gauge text {{ font-family:{SANS}; fill:#f1f4f8; }}
.gauge .unit {{ fill:#8197b6; }}
.gauge.good .val {{ stroke:#4ade80; }}
.gauge.warning .val {{ stroke:#f5b740; }}
.gauge.critical .val {{ stroke:#f87171; }}
.verdict-label {{ font-size:11px; font-weight:600; color:#8197b6; text-transform:uppercase; letter-spacing:.09em; }}
.verdict-level {{ font-size:21px; font-weight:650; margin:6px 0 4px; letter-spacing:-.01em; }}
.verdict-level.good {{ color:#4ade80; }} .verdict-level.warning {{ color:#f5b740; }} .verdict-level.critical {{ color:#f87171; }}
.verdict-period {{ font-size:13px; color:#a9b8cc; }}

/* sticky nav */
nav.sections {{ position:sticky; top:0; z-index:5; background:var(--surface); border-bottom:1px solid var(--line);
  box-shadow:0 1px 2px var(--shadow); }}
nav.sections .wrap {{ display:flex; align-items:center; gap:4px; overflow-x:auto; }}
nav.sections a {{ color:var(--muted); text-decoration:none; font-size:13.5px; font-weight:500; padding:14px 12px 12px;
  white-space:nowrap; border-bottom:2px solid transparent; transition:color .15s, border-color .15s; }}
nav.sections a:hover {{ color:var(--text); border-bottom-color:var(--accent); }}
.theme-btn {{ margin-left:auto; flex:none; font:500 12.5px/1 {SANS}; color:var(--muted); background:transparent;
  border:1px solid var(--line); border-radius:4px; padding:7px 11px; cursor:pointer; }}
.theme-btn:hover {{ color:var(--text); border-color:var(--muted); }}

/* sections */
section {{ margin:48px 0 0; scroll-margin-top:60px; }}
.section-head {{ padding-bottom:8px; border-bottom:1px solid var(--line); }}
h2 {{ font-size:21px; margin:0; letter-spacing:-.01em; font-weight:650; }}
.sub {{ color:var(--muted); font-size:14px; margin:10px 0 18px; max-width:820px; }}
.muted {{ color:var(--muted); }} .small {{ font-size:13px; }}
.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:6px; box-shadow:0 1px 2px var(--shadow); }}

/* risk cards */
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(310px,100%),1fr)); gap:16px; }}
.card {{ padding:20px; display:flex; flex-direction:column; gap:12px; }}
.card.is-target {{ border-color:color-mix(in srgb, var(--accent) 55%, var(--line));
  box-shadow:inset 0 3px 0 var(--accent),0 1px 2px var(--shadow); }}
.card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }}
.card-name {{ font-size:18px; font-weight:650; letter-spacing:-.01em; }}
.tag {{ font-size:10.5px; font-weight:600; letter-spacing:.07em; text-transform:uppercase; color:var(--accent);
  background:var(--accent-bg); border-radius:3px; padding:3px 6px; margin-left:8px; vertical-align:2px; }}
.period {{ font-size:13px; color:var(--muted); margin-top:2px; }}
.score {{ text-align:right; line-height:1; }}
.score b {{ font-size:30px; font-weight:650; }} .score span {{ font-size:12px; color:var(--muted); }}
.badge {{ align-self:flex-start; display:inline-flex; align-items:center; gap:6px; padding:3px 10px 3px 4px;
  border-radius:999px; font-size:12px; font-weight:600; }}
.badge .icon {{ display:inline-grid; place-items:center; width:17px; height:17px; border-radius:50%;
  color:var(--on-status); font-size:10px; font-weight:800; }}
.badge.good {{ background:var(--good-bg); color:var(--good); }} .badge.good .icon {{ background:var(--good); }}
.badge.warning {{ background:var(--warning-bg); color:var(--warning); }} .badge.warning .icon {{ background:var(--warning); }}
.badge.critical {{ background:var(--critical-bg); color:var(--critical); }} .badge.critical .icon {{ background:var(--critical); }}
.meter {{ display:grid; grid-template-columns:repeat({METER_CELLS},1fr); gap:3px; }}
.meter i {{ height:6px; border-radius:1px; background:var(--track); }}
.meter.good i.on {{ background:var(--good); }}
.meter.warning i.on {{ background:var(--warning); }}
.meter.critical i.on {{ background:var(--critical); }}
.meter-scale {{ display:grid; grid-template-columns:3fr 3fr 4fr; font-size:10.5px; letter-spacing:.06em;
  text-transform:uppercase; color:var(--faint); margin-top:-4px; }}
.reasons {{ list-style:none; margin:4px 0 0; padding:12px 0 0; display:flex; flex-direction:column; gap:9px;
  border-top:1px solid var(--line); }}
.reasons li {{ display:flex; gap:10px; align-items:baseline; font-size:14px; }}
.pts {{ flex:none; font-size:11.5px; font-weight:650; color:var(--muted); border:1px solid var(--line);
  border-radius:3px; padding:0 5px; line-height:1.6; }}
.reasons li.more, .reasons li.ok {{ color:var(--muted); }}

/* snapshot tiles */
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(230px,100%),1fr)); gap:16px; }}
.tile {{ padding:16px 18px; display:flex; flex-direction:column; gap:6px; }}
.tile-label {{ font-size:11.5px; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); }}
.tile-row {{ display:flex; justify-content:space-between; align-items:flex-end; gap:8px; }}
.tile-value {{ font-size:28px; font-weight:650; line-height:1.15; letter-spacing:-.01em; }}
.delta {{ font-size:12.5px; font-weight:600; }} .delta.up {{ color:var(--good); }} .delta.down {{ color:var(--critical); }}
.delta.flat {{ color:var(--muted); }}
.spark {{ width:110px; height:32px; overflow:visible; }}
.spark path {{ stroke:var(--accent); }} .spark circle {{ fill:var(--accent); }}

/* tables */
.table-wrap {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums; }}
th, td {{ padding:10px 14px; text-align:right; border-bottom:1px solid var(--line); white-space:nowrap; }}
td {{ font-size:13.5px; }}
th:first-child, td:first-child {{ text-align:left; }}
thead th {{ color:var(--muted); font-size:11px; font-weight:600; letter-spacing:.06em; text-transform:uppercase;
  vertical-align:bottom; background:var(--surface-2); border-bottom-color:color-mix(in srgb, var(--muted) 35%, var(--line)); }}
thead th:first-child {{ border-top-left-radius:5px; }} thead th:last-child {{ border-top-right-radius:5px; }}
thead th .co {{ font-size:13px; font-weight:600; text-transform:none; letter-spacing:0; color:var(--text); }}
thead th.target .co {{ color:var(--accent); }}
thead th .th-sub {{ display:block; font-weight:400; font-size:10.5px; color:var(--faint); text-transform:none; letter-spacing:0; }}
tbody tr:last-child td {{ border-bottom:none; }}
tbody tr:hover td {{ background:var(--surface-2); }}
td.target, th.target {{ background:var(--accent-bg) !important; color:var(--text); font-weight:650; }}
th.target {{ color:var(--accent); }}
.mark {{ font-size:10px; margin-left:5px; }} .mark.better {{ color:var(--good); }} .mark.worse {{ color:var(--critical); }}
.dagger {{ color:var(--warning); font-weight:700; }}
.nm {{ color:var(--faint); cursor:help; }}
.note {{ color:var(--muted); font-size:13px; margin:12px 2px 0; }}

/* charts */
.legend {{ display:flex; gap:18px; flex-wrap:wrap; font-size:13px; margin:0 0 14px; color:var(--muted); }}
.legend span {{ display:inline-flex; align-items:center; gap:8px; }}
.legend i, .tip .key {{ display:inline-block; width:16px; height:3px; border-radius:2px; }}
.charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(460px,100%),1fr)); gap:16px; }}
.chart-card {{ padding:18px 18px 10px; }}
.chart-card h3 {{ font-size:15px; margin:0; font-weight:650; }}
.chart-card p {{ margin:3px 0 8px; font-size:12px; color:var(--faint); }}
figure.chart {{ margin:0; outline:none; }}
figure.chart:focus-visible {{ box-shadow:0 0 0 2px var(--accent); border-radius:4px; }}
.plot {{ position:relative; }}
.plot svg {{ width:100%; height:auto; display:block; overflow:visible; }}
svg .grid {{ stroke:var(--grid); stroke-width:1; }} svg .zero {{ stroke:var(--faint); stroke-width:1; }}
svg .ref {{ stroke:var(--warning); stroke-dasharray:4 4; opacity:.6; }}
svg .tick {{ fill:var(--faint); font-size:11.5px; font-family:{SANS}; font-variant-numeric:tabular-nums; }}
svg .end {{ fill:var(--text); font-size:12.5px; font-family:{SANS}; }} svg .endv {{ font-weight:650; }}
svg .dot {{ stroke:var(--surface); stroke-width:2; }}
svg .xh {{ stroke:var(--muted); stroke-width:1; stroke-dasharray:2 3; opacity:0; pointer-events:none; }}
.tip {{ position:absolute; top:4px; min-width:180px; background:var(--surface); border:1px solid var(--line);
  border-radius:6px; padding:9px 11px; box-shadow:0 8px 24px -6px var(--shadow);
  font-size:12.5px; line-height:1.4; pointer-events:none; z-index:2; }}
.tip-h {{ color:var(--muted); font-size:11px; font-weight:600; margin-bottom:5px; text-transform:uppercase; letter-spacing:.06em; }}
.tip-r {{ display:flex; align-items:center; gap:8px; margin:3px 0; }} .tip-r span:last-child {{ color:var(--muted); }}
details.data {{ margin:6px 0 4px; }} details.data summary {{ font-size:12px; color:var(--faint); cursor:pointer; }}
details.data summary:hover {{ color:var(--accent); }}
details.data table {{ font-size:12px; margin-top:6px; }} details.data td, details.data th {{ padding:6px 8px; }}
details.data .fy {{ display:block; color:var(--faint); font-size:10px; }}

/* notes and details */
.notes {{ display:flex; flex-direction:column; gap:10px; }}
.note-item {{ display:flex; gap:12px; padding:13px 16px; background:var(--note-bg); border-radius:4px; font-size:14px;
  border:1px solid var(--line); border-left:3px solid var(--accent); }}
.note-item.caution {{ border-left-color:var(--warning); background:var(--warning-bg); }}
.note-item.caution .i {{ background:var(--warning); color:var(--on-status); }}
.note-item .i {{ flex:none; width:18px; height:18px; border-radius:50%; background:var(--accent-bg);
  color:var(--accent); display:grid; place-items:center; font-size:11px; font-weight:700; margin-top:1px; }}
.note-item details {{ display:inline; }}
.note-item details summary {{ display:inline; cursor:pointer; color:var(--link); font-size:13px; margin-left:6px; }}
.note-item details[open] {{ display:block; }}
.note-item details p {{ margin:8px 0 0; color:var(--muted); font-size:13px; }}
details.section {{ padding:0; margin-bottom:10px; }}
details.section > summary {{ cursor:pointer; font-weight:600; padding:14px 18px; list-style:none; display:flex;
  justify-content:space-between; align-items:center; }}
details.section > summary::-webkit-details-marker {{ display:none; }}
details.section > summary::after {{ content:"+"; color:var(--muted); font-size:18px; font-weight:400; line-height:1; }}
details.section[open] > summary::after {{ content:"\\2212"; }}
details.section > summary:hover::after {{ color:var(--accent); }}
details.section > .body {{ padding:0 18px 16px; }}
th.left, td.left {{ text-align:left; }}
td .th-sub {{ display:block; font-size:11.5px; color:var(--faint); font-weight:400; }}
.small-badge {{ font-size:11px; padding:2px 8px 2px 3px; }} .small-badge .icon {{ width:15px; height:15px; font-size:9px; }}
td.wrap {{ white-space:normal; text-align:left; min-width:240px; font-size:14px; }}
td.industry {{ white-space:normal; min-width:220px; }}
footer {{ margin:56px 0 40px; padding-top:16px; border-top:1px solid var(--line); color:var(--faint);
  font-size:12.5px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
@media (max-width:640px) {{ .wrap {{ padding:0 16px; }} h1 {{ font-size:32px; }} .verdict {{ width:100%; min-width:0; }}
  .charts {{ grid-template-columns:1fr; }} }}
@media (prefers-reduced-motion:reduce) {{ *, *::before, *::after {{ animation:none !important; transition:none !important; }} }}
@media print {{ nav.sections {{ display:none; }} .panel {{ box-shadow:none; break-inside:avoid; }} }}
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


def _section(sid: str, title: str, subtitle: str, body: str) -> str:
    return (f'<section id="{sid}"><div class="section-head"><h2>{title}</h2></div>'
            f'<p class="sub">{subtitle}</p>{body}</section>')


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
             f'<text class="unit" x="54" y="76" text-anchor="middle" font-size="10">of {METER_CELLS}+ pts</text></svg>')
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
    nav = "".join(f'<a href="#{sid}">{escape(label)}</a>' for sid, label in (
        ("glance", "At a glance"), ("snapshot", f"{result.target} snapshot"), ("companies", "Companies"),
         ("trends", "Trends"), ("peers", "Peers"), ("notes", "Keep in mind"), ("detail", "More detail")))
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
{_section("glance", "Risk at a glance", "Flags point to unusual financial patterns worth a closer look. They are "
          "not a finding of fraud or a share-price forecast. Many rules compare each company with the others here, "
          "so a different peer group can change the scores.", _financial_banner(result) + _cards(result, notes))}
{_section("snapshot", f"{escape(result.target)} snapshot",
          f"{escape(result.period_label(result.target, year))}, compared with the prior year and with peers.",
          _snapshot(result))}
{_section("companies", "Companies compared", "Peers are checked against the SEC's industry classification. "
          "Fiscal years end on different dates, so each company keeps its own label.", _companies_table(result, year))}
{_section("trends", "Trends", "By comparison year. Hover or focus a chart to see every company's value and fiscal "
          "year.", trends + f'<div style="margin-top:16px">{more_charts}</div>')}
{_section("peers", "Peer comparison", f"Comparison year {year}.", _peer_table(result))}
{_section("notes", "Keep in mind", "Differences in how the companies report that affect the comparison.",
          _keep_in_mind(result))}
{_section("detail", "More detail", "The full workbook, <strong>financial_report.xlsx</strong>, is in this folder.",
          _events(result) + _methodology(result))}

<footer><span>Generated {date.today():%B} {date.today().day}, {date.today().year} from SEC EDGAR filings</span><span>Not investment advice.</span></footer>
</main>
<script>{svg.CHART_SCRIPT}{THEME_SCRIPT}</script>
</body></html>"""
    path.write_text(page, encoding="utf-8")
    return path
