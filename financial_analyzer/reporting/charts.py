"""Trend charts (PNG) for each metric and for the risk score.

The x-axis is the comparison year; every label names the company's own reported
fiscal year, and a footnote gives each company's latest period end.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from ..metrics import METRICS_BY_KEY  # noqa: E402
from ..standardize import long_date  # noqa: E402

# Validated categorical order (light surface); color follows the company, target first.
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"


def company_colors(names: list[str]) -> dict[str, str]:
    return {name: SERIES_COLORS[i % len(SERIES_COLORS)] for i, name in enumerate(names)}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _formatter(fmt: str) -> FuncFormatter:
    if fmt == "pct":
        return FuncFormatter(lambda v, _: f"{v * 100:.0f}%")
    if fmt in ("days", "score"):
        return FuncFormatter(lambda v, _: f"{v:.0f}")
    return FuncFormatter(lambda v, _: f"{v:.1f}x")


def _label_text(value: float, fmt: str) -> str:
    if fmt == "pct":
        return f"{value * 100:.1f}%"
    if fmt == "days":
        return f"{value:.0f}d"
    if fmt == "score":
        return f"{value:.0f} pts"
    return f"{value:.2f}x"


def _spread_labels(positions: list[float], min_gap: float) -> list[float]:
    """Nudge end-of-line label positions apart so they do not overlap."""
    order = sorted(range(len(positions)), key=lambda i: positions[i])
    placed = [0.0] * len(positions)
    last = None
    for i in order:
        y = positions[i] if last is None else max(positions[i], last + min_gap)
        placed[i] = last = y
    return placed


def period_footnote(result, year: int) -> list[str]:
    """One line per company: 'Toyota FY2026 · Year ended March 31, 2026 · Comparison period: 2025'."""
    lines = []
    for name in result.company_names:
        p = result.period(name, year)
        if p is not None:
            lines.append(f"{name} {p.label} · Year ended {long_date(p.end)} · Comparison period: {year}")
    return lines


def line_chart(series: dict[str, pd.Series], title: str, subtitle: str, fmt: str, colors: dict[str, str],
               path: Path, end_labels: dict[str, str], footnotes: list[str], target: str | None = None,
               zero_line: bool = False, reference_lines: tuple[tuple[float, str], ...] = ()) -> Path:
    """series are indexed by comparison year; end_labels maps company -> reported label of its latest point."""
    height = 4.0 + 0.16 * len(footnotes)
    fig, ax = plt.subplots(figsize=(7.4, height), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)

    all_years = sorted({y for s in series.values() for y in s.dropna().index})
    x_max = all_years[-1] if all_years else None
    ends, gaps = [], []
    for name, full in series.items():
        s = full.dropna()
        if s.empty:
            continue
        width = 2.4 if name == target else 2.0
        # Plot on the full year range so missing periods break the line instead of being bridged.
        line = full.reindex(all_years)
        ax.plot(line.index, line.values, color=colors[name], linewidth=width, marker="o", markersize=5,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=name, zorder=3 if name == target else 2)
        if s.index[-1] == x_max:
            ends.append((name, s.index[-1], s.values[-1]))
        else:
            gaps.append(name)

    if zero_line:
        ax.axhline(0, color=TEXT_SECONDARY, linewidth=0.8, zorder=1)
    if all_years:
        for y, text in reference_lines:
            ax.hlines(y, all_years[0], x_max, color=TEXT_SECONDARY, linewidth=0.8, linestyle=(0, (3, 3)), zorder=1)
            ax.annotate(text, xy=(0, y), xycoords=("axes fraction", "data"), xytext=(2, 3),
                        textcoords="offset points", fontsize=7.5, color=TEXT_SECONDARY)
    ax.yaxis.set_major_formatter(_formatter(fmt))
    ax.set_xticks(all_years)
    ax.set_xlabel("Comparison year", fontsize=8.5, color=TEXT_SECONDARY)
    ax.margins(x=0.04)
    if fmt == "score":
        ax.set_ylim(bottom=0)

    # Direct labels at line ends (company, reported fiscal year, latest value), spread to avoid collisions.
    if ends:
        lo, hi = ax.get_ylim()
        placed = _spread_labels([e[2] for e in ends], (hi - lo) * 0.075)
        ax.set_xlim(right=x_max + 1.25)
        for (name, x, y), y_label in zip(ends, placed):
            ax.annotate(f"{name} {end_labels.get(name, '')} {_label_text(y, fmt)}".replace("  ", " "),
                        xy=(x, y), xytext=(x + 0.12, y_label), fontsize=8.5, color=TEXT_PRIMARY, va="center",
                        fontweight="bold" if name == target else "normal")

    notes = list(footnotes)
    for name in gaps:
        notes.append(f"{name} {end_labels.get(name, '')}: no value for the latest period (see the metric definition)."
                     .replace("  ", " "))

    fig.text(0.012, 1 - 0.14 / height, title, fontsize=12, fontweight="bold", color=TEXT_PRIMARY, va="top")
    fig.text(0.012, 1 - 0.42 / height, subtitle, fontsize=8.5, color=TEXT_SECONDARY, va="top")
    legend_y = -0.22
    ax.legend(loc="upper left", bbox_to_anchor=(0, legend_y), ncol=len(series), frameon=False, fontsize=8.5,
              labelcolor=TEXT_SECONDARY, handlelength=1.8)
    for i, line in enumerate(notes):
        fig.text(0.012, (0.16 * (len(notes) - i) - 0.04) / height, line, fontsize=7.5, color=TEXT_SECONDARY)
    bottom = (0.95 + 0.16 * len(notes)) / height
    top = 1 - (0.75 + 0.16 * subtitle.count("\n")) / height
    fig.subplots_adjust(left=0.08, right=0.97, top=top, bottom=bottom)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def _end_labels(result, year: int) -> dict[str, str]:
    return {name: (result.period(name, year).label if result.period(name, year) else "")
            for name in result.company_names}


def metric_charts(result, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    colors = company_colors(result.company_names)
    year = result.latest_year
    footnotes = period_footnote(result, year)
    paths = {}
    for key in result.profile.metric_keys:
        metric = METRICS_BY_KEY[key]
        series = {name: result.metrics.xs(name, level="company")[key] for name in result.company_names}
        subtitle = metric.formula
        if result.blocked(key, result.company_names):
            subtitle += "\n† Not directly comparable across companies - see the comparability warnings"
        paths[key] = line_chart(series, metric.label, subtitle, metric.fmt, colors, out_dir / f"{key}.png",
                                _end_labels(result, year), footnotes, target=result.target,
                                zero_line=metric.fmt == "pct")
    return paths


def score_chart(result, out_dir: Path) -> Path:
    colors = company_colors(result.company_names)
    scores = result.scores.pivot(index="comparison_year", columns="company", values="score")
    series = {name: scores[name].astype(float) for name in result.company_names if name in scores}
    year = result.latest_year
    fig_path = out_dir / "risk_score.png"
    line_chart(series, "Risk score by comparison year",
               "Sum of points from triggered rules (0-2 lower, 3-5 moderate, 6+ elevated)",
               "score", colors, fig_path, _end_labels(result, year), period_footnote(result, year),
               target=result.target, reference_lines=((3, "Moderate"), (6, "Elevated")))
    return fig_path
