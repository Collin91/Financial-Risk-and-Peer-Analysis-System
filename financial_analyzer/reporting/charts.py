"""Trend charts (PNG) for each metric and for the risk score."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from ..metrics import METRICS_BY_KEY  # noqa: E402

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


def line_chart(series: dict[str, pd.Series], title: str, subtitle: str, fmt: str, colors: dict[str, str],
               path: Path, target: str | None = None, zero_line: bool = False,
               reference_lines: tuple[tuple[float, str], ...] = ()) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 3.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)

    ends = []
    for name, s in series.items():
        s = s.dropna()
        if s.empty:
            continue
        width = 2.4 if name == target else 2.0
        ax.plot(s.index, s.values, color=colors[name], linewidth=width, marker="o", markersize=5,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=name, zorder=3 if name == target else 2)
        ends.append((name, s.index[-1], s.values[-1]))

    if zero_line:
        ax.axhline(0, color=TEXT_SECONDARY, linewidth=0.8, zorder=1)
    if ends:
        x_lo = min(s.dropna().index.min() for s in series.values() if not s.dropna().empty)
        x_hi = max(e[1] for e in ends)
    for y, text in reference_lines:
        ax.hlines(y, x_lo, x_hi, color=TEXT_SECONDARY, linewidth=0.8, linestyle=(0, (3, 3)), zorder=1)
        ax.annotate(text, xy=(0, y), xycoords=("axes fraction", "data"), xytext=(2, 3), textcoords="offset points",
                    fontsize=7.5, color=TEXT_SECONDARY)
    ax.yaxis.set_major_formatter(_formatter(fmt))
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.margins(x=0.04)
    if fmt == "score":
        ax.set_ylim(bottom=0)

    # Direct labels at line ends (company + latest value), spread to avoid collisions.
    if ends:
        lo, hi = ax.get_ylim()
        placed = _spread_labels([e[2] for e in ends], (hi - lo) * 0.075)
        x_max = max(e[1] for e in ends)
        ax.set_xlim(right=x_max + 0.9)
        for (name, x, y), y_label in zip(ends, placed):
            ax.annotate(f"{name} {_label_text(y, fmt)}", xy=(x, y), xytext=(x + 0.12, y_label),
                        fontsize=8.5, color=TEXT_PRIMARY, va="center",
                        fontweight="bold" if name == target else "normal")

    fig.text(0.012, 0.96, title, fontsize=12, fontweight="bold", color=TEXT_PRIMARY, va="top")
    fig.text(0.012, 0.885, subtitle, fontsize=8.5, color=TEXT_SECONDARY, va="top")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.08), ncol=len(series), frameon=False, fontsize=8.5,
              labelcolor=TEXT_SECONDARY, handlelength=1.8)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.80, bottom=0.2)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def metric_charts(result, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    colors = company_colors(result.company_names)
    paths = {}
    for key in result.profile.metric_keys:
        metric = METRICS_BY_KEY[key]
        series = {name: result.metrics.xs(name, level="company")[key] for name in result.company_names}
        paths[key] = line_chart(
            series, metric.label, metric.formula, metric.fmt, colors, out_dir / f"{key}.png",
            target=result.target, zero_line=metric.fmt == "pct",
        )
    return paths


def score_chart(result, out_dir: Path) -> Path:
    colors = company_colors(result.company_names)
    scores = result.scores.pivot(index="fiscal_year", columns="company", values="score")
    series = {name: scores[name].astype(float) for name in result.company_names if name in scores}
    fig_path = out_dir / "risk_score.png"
    line_chart(series, "Risk score by year", "Sum of points from triggered rules (0-2 lower, 3-5 moderate, 6+ elevated)",
               "score", colors, fig_path, target=result.target,
               reference_lines=((3, "Moderate"), (6, "Elevated")))
    return fig_path
