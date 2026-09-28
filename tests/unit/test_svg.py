"""Inline SVG charts on the summary page."""

import json
import re
from html import unescape

import pandas as pd

from financial_analyzer.reporting import svg


def _chart(names):
    series = {n: pd.Series({2024: 0.05, 2025: 0.04 + i / 100}) for i, n in enumerate(names)}
    labels = {n: {2024: "FY2024", 2025: "FY2025"} for n in names}
    colors = {n: svg.series_var(i) for i, n in enumerate(names)}
    return svg.line_chart("c", series, labels, "pct", colors)


def _plot_right_edge(html: str) -> float:
    xs = [float(x) for x in re.findall(r'<line class="grid" x1="[\d.]+" x2="([\d.]+)"', html)]
    return max(xs)


def test_long_company_names_get_room_for_end_labels():
    short = _chart(["Ford", "GM"])
    long = _chart(["Ford", "General Motors Company"])
    assert _plot_right_edge(long) < _plot_right_edge(short)
    widest = len("5.0% General Motors Company FY2025") * svg.CHAR_W
    assert svg.W - _plot_right_edge(long) >= widest


def test_missing_values_break_the_line_and_appear_as_na_in_tooltip_data():
    series = {"Ford": pd.Series({2023: 0.03, 2024: float("nan"), 2025: 0.02})}
    html = svg.line_chart("c", series, {"Ford": {}}, "pct", {"Ford": "--s1"})
    assert html.count("<path") == 2  # two segments, not one bridged line
    data = json.loads(unescape(re.search(r'data-chart="([^"]+)"', html).group(1)))
    assert data["series"][0]["vals"][1] is None
