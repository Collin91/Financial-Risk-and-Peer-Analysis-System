"""Inline SVG charts for the HTML summary page.

Crisp at any size, follow the page's light/dark theme (colors are CSS variables), and
carry their data for the hover layer: a crosshair snaps to the nearest comparison year
and one tooltip lists every company with its own reported fiscal-year label.
"""

from __future__ import annotations

import json
import math
from html import escape

import pandas as pd

from financial_analyzer.analysis.metrics import format_value

W, H = 560, 280
LEFT, TOP, BOTTOM = 44, 12, 30
CHAR_W = 6.9  # approximate width of one end-label character at 13px
SERIES_VARS = [f"--s{i}" for i in range(1, 9)]


def series_var(i: int) -> str:
    return SERIES_VARS[i % len(SERIES_VARS)]


def nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    raw = (hi - lo) / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v <= hi + step * 0.5:
        ticks.append(round(v, 10))
        v += step
    if ticks[-1] < hi:
        ticks.append(round(ticks[-1] + step, 10))
    return ticks


def _tick_label(v: float, fmt: str, step: float, top: float = 0.0) -> str:
    """top: the largest absolute value on the axis (sets the dollar unit)."""
    if fmt == "pct":
        return f"{v * 100:.{0 if step * 100 >= 1 else 1}f}%"
    if fmt in ("days", "score"):
        return f"{v:.0f}"
    if fmt == "usd":  # $100B, $2.5B, $500M; one unit per axis, chosen from its largest value
        if v == 0:
            return "$0"
        div, unit = next((d, u) for d, u in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1, "")) if top >= d or d == 1)
        return f"{'-' if v < 0 else ''}${abs(v) / div:.{0 if step / div >= 1 else 1}f}{unit}"
    return f"{v:.{1 if step >= 0.1 else 2}f}x"


def value_text(v: float, fmt: str) -> str:
    if fmt == "score":
        return f"{v:.0f} pt{'' if round(v) == 1 else 's'}"
    return format_value(v, fmt)


def _spread(ys: list[float], gap: float, lo: float, hi: float) -> list[float]:
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    last = None
    for i in order:
        out[i] = max(ys[i], last + gap) if last is not None else ys[i]
        last = out[i]
    overflow = max(0.0, (max(out) if out else 0) - hi)
    return [max(lo, y - overflow) for y in out]


def line_chart(chart_id: str, series: dict[str, pd.Series], labels: dict[str, dict[int, str]], fmt: str,
               colors: dict[str, str], target: str | None = None, zero_line: bool = False,
               reference_lines: tuple[tuple[float, str], ...] = (), title: str = "",
               blanks: dict[str, dict[int, str]] | None = None) -> str:
    """series: company -> values by comparison year; labels: company -> {year: 'FY2026'};
    blanks: company -> {year: text shown instead of "n/a" where a value is missing for a known reason}."""
    blanks = blanks or {}
    present = sorted({int(y) for s in series.values() for y in s.dropna().index})
    if not present:
        return '<p class="muted">No data.</p>'
    # A continuous axis: a year with no value for any company still gets its slot, so lines break there.
    years = list(range(present[0], present[-1] + 1))
    values = [float(v) for s in series.values() for v in s.dropna().values] + [r[0] for r in reference_lines]
    lo, hi = min(values), max(values)
    if zero_line or fmt == "score":
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    ticks = nice_ticks(lo, hi)
    y0, y1 = ticks[0], ticks[-1]
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
    longest = max((len(f"{value_text(float(s.dropna().iloc[-1]), fmt)} {n} {labels.get(n, {}).get(years[-1], '')}")
                   for n, s in series.items() if not s.dropna().empty), default=10)
    right = min(max(90, 16 + longest * CHAR_W), 240)  # room for the end labels, whatever the company names
    pw, ph = W - LEFT - right, H - TOP - BOTTOM

    def x(year: int) -> float:
        return LEFT + (pw * (years.index(year) / (len(years) - 1)) if len(years) > 1 else pw / 2)

    def y(v: float) -> float:
        return TOP + ph * (1 - (v - y0) / (y1 - y0))

    parts = []
    for t in ticks:  # recessive grid and y labels
        parts.append(f'<line class="grid" x1="{LEFT}" x2="{LEFT + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                     f'<text class="tick" x="{LEFT - 8}" y="{y(t) + 4:.1f}" text-anchor="end">'
                     f'{_tick_label(t, fmt, step, max(abs(ticks[0]), abs(ticks[-1])))}</text>')
    for yr in years:
        parts.append(f'<text class="tick" x="{x(yr):.1f}" y="{H - 8}" text-anchor="middle">{yr}</text>')
    if zero_line and y0 < 0 < y1:
        parts.append(f'<line class="zero" x1="{LEFT}" x2="{LEFT + pw}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    for ref, text in reference_lines:
        parts.append(f'<line class="ref" x1="{LEFT}" x2="{LEFT + pw}" y1="{y(ref):.1f}" y2="{y(ref):.1f}"/>'
                     f'<text class="tick" x="{LEFT + 4}" y="{y(ref) - 5:.1f}">{escape(text)}</text>')

    ends, data_series = [], []
    ordered = sorted(series, key=lambda n: n == target)  # target drawn last, on top
    for name in ordered:
        s = series[name]
        color = colors[name]
        segments, current = [], []
        for yr in years:
            v = s.get(yr)
            if v is None or pd.isna(v):
                if current:
                    segments.append(current)
                current = []
            else:
                current.append((x(yr), y(float(v))))
        if current:
            segments.append(current)
        width = 2.5 if name == target else 2
        for seg in segments:
            d = " ".join(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}" for i, (px, py) in enumerate(seg))
            parts.append(f'<path class="line{" tgt" if name == target else ""}" d="{d}" fill="none" '
                         f'stroke="var({color})" stroke-width="{width}" '
                         f'stroke-linejoin="round" stroke-linecap="round"/>')
            parts += [f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="var({color})" class="dot"/>' for px, py in seg]
        last = s.get(years[-1])
        if last is not None and not pd.isna(last):
            ends.append((name, float(last)))
    for name in series:
        s = series[name]
        data_series.append({
            "name": name, "color": colors[name],
            "vals": [_tip_value(s.get(yr), blanks.get(name, {}).get(yr), labels.get(name, {}).get(yr, ""), fmt)
                     for yr in years],
        })

    placed = _spread([y(v) for _, v in ends], 17, TOP + 6, TOP + ph)
    for (name, v), py in zip(ends, placed):
        label = f"{name} {labels.get(name, {}).get(years[-1], '')}".strip()
        weight = ' font-weight="600"' if name == target else ""
        parts.append(f'<text class="end" x="{x(years[-1]) + 10:.1f}" y="{py + 4:.1f}"{weight}>'
                     f'<tspan class="endv">{value_text(v, fmt)}</tspan> {escape(label)}</text>')

    parts.append(f'<line class="xh" x1="0" x2="0" y1="{TOP}" y2="{TOP + ph}"/>')
    data = {"x": [round(x(yr), 1) for yr in years], "years": years, "series": data_series}
    svg = (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)} by comparison year">'
           f'{"".join(parts)}</svg>')
    table = _data_table(years, series, labels, fmt, blanks)
    return (f'<figure class="chart" id="{chart_id}" tabindex="0" data-chart="{escape(json.dumps(data))}">'
            f'<div class="plot">{svg}<div class="tip" hidden></div></div>'
            f'<details class="data"><summary>Show data</summary>{table}</details></figure>')


def _missing(v) -> bool:
    return v is None or pd.isna(v)


def _tip_value(v, blank: str | None, label: str, fmt: str) -> dict | None:
    if _missing(v):
        return {"t": blank, "l": label} if blank else None
    return {"t": value_text(float(v), fmt), "l": label}


def _data_table(years: list[int], series: dict[str, pd.Series], labels, fmt: str,
                blanks: dict[str, dict[int, str]]) -> str:
    head = "".join(f"<th>{yr}</th>" for yr in years)
    rows = ""
    for name, s in series.items():
        cells = "".join(
            f"<td>{escape(blanks.get(name, {}).get(yr, 'n/a')) if _missing(s.get(yr)) else value_text(float(s.get(yr)), fmt)}"
            f"<span class='fy'>{labels.get(name, {}).get(yr, '')}</span></td>" for yr in years)
        rows += f"<tr><td>{escape(name)}</td>{cells}</tr>"
    return f'<table><thead><tr><th>Company</th>{head}</tr></thead><tbody>{rows}</tbody></table>'


def sparkline(values: list[float]) -> str:
    """Tiny trend line for a stat tile: history in the muted tone, latest point in the accent."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None and not pd.isna(v)]
    if len(pts) < 2:
        return ""
    w, h, pad = 120, 32, 4
    vs = [v for _, v in pts]
    lo, hi = min(vs), max(vs)
    span = (hi - lo) or 1

    def px(i):
        return pad + (w - 2 * pad) * i / (len(values) - 1)

    def py(v):
        return pad + (h - 2 * pad) * (1 - (v - lo) / span)

    d = " ".join(f"{'M' if k == 0 else 'L'}{px(i):.1f},{py(v):.1f}" for k, (i, v) in enumerate(pts))
    li, lv = pts[-1]
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" aria-hidden="true"><path d="{d}" fill="none" '
            f'stroke="var(--muted)" stroke-width="1.5"/><circle cx="{px(li):.1f}" cy="{py(lv):.1f}" r="3" '
            f'fill="var(--s1)"/></svg>')


CHART_SCRIPT = """
document.querySelectorAll('figure.chart').forEach(function (fig) {
  var data = JSON.parse(fig.dataset.chart);
  var svg = fig.querySelector('svg'), xh = svg.querySelector('.xh'), tip = fig.querySelector('.tip');
  var plot = fig.querySelector('.plot'), idx = -1;
  function show(i) {
    idx = i;
    var x = data.x[i];
    xh.setAttribute('x1', x); xh.setAttribute('x2', x); xh.style.opacity = 1;
    tip.replaceChildren();
    var head = document.createElement('div');
    head.className = 'tip-h'; head.textContent = 'Comparison year ' + data.years[i];
    tip.append(head);
    data.series.forEach(function (s) {
      var v = s.vals[i], row = document.createElement('div'), key = document.createElement('span');
      var val = document.createElement('strong'), name = document.createElement('span');
      row.className = 'tip-r'; key.className = 'key'; key.style.background = 'var(' + s.color + ')';
      val.textContent = v ? v.t : 'n/a';
      name.textContent = s.name + (v && v.l ? ' ' + v.l : '');
      row.append(key, val, name); tip.append(row);
    });
    tip.hidden = false;
    var r = svg.getBoundingClientRect(), px = x / svg.viewBox.baseVal.width * r.width;
    var left = px + 14;
    if (left + tip.offsetWidth > r.width) left = px - 14 - tip.offsetWidth;
    tip.style.left = Math.max(0, left) + 'px';
  }
  function hide() { tip.hidden = true; xh.style.opacity = 0; }
  svg.addEventListener('pointermove', function (e) {
    var r = svg.getBoundingClientRect(), vx = (e.clientX - r.left) / r.width * svg.viewBox.baseVal.width, best = 0;
    data.x.forEach(function (x, i) { if (Math.abs(x - vx) < Math.abs(data.x[best] - vx)) best = i; });
    show(best);
  });
  svg.addEventListener('pointerleave', hide);
  fig.addEventListener('focus', function () { show(data.x.length - 1); });
  fig.addEventListener('blur', hide);
  fig.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft' && idx > 0) show(idx - 1);
    if (e.key === 'ArrowRight' && idx < data.x.length - 1) show(idx + 1);
  });
});
"""
