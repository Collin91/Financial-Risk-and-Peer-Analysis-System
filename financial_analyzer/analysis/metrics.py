"""Financial ratios computed from standardized line items.

Ratios and growth rates use reporting-currency amounts, so exchange-rate moves do
not distort a foreign filer's growth or margins. USD amounts are used only where
absolute size is shown.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from financial_analyzer.data.standardize import CompanyFinancials


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    fmt: str  # "pct", "ratio" (x.xx), "days"
    higher_is_better: bool | None  # None = no inherent direction
    formula: str


METRICS = [
    Metric("revenue_growth", "Revenue growth", "pct", True, "Revenue / prior-year revenue - 1 (reporting currency)"),
    Metric("gross_margin", "Gross margin", "pct", True, "(Revenue - cost of revenue) / revenue"),
    Metric("operating_margin", "Operating margin", "pct", True, "Operating income / revenue"),
    Metric("net_margin", "Net margin", "pct", True, "Net income attributable to parent / revenue"),
    Metric("current_ratio", "Current ratio", "ratio", True, "Current assets / current liabilities"),
    Metric("liabilities_to_assets", "Liabilities-to-assets", "pct", False, "Total liabilities / total assets"),
    Metric("roa", "Return on assets", "pct", True, "Net income / average total assets"),
    Metric("asset_turnover", "Asset turnover", "ratio", True, "Revenue / average total assets"),
    Metric("fcf_margin", "Free-cash-flow margin", "pct", True,
           "(Reported operating cash flow - PP&E capex) / revenue"),
    Metric("capex_pct_revenue", "Capex % of revenue", "pct", None, "PP&E capital expenditures / revenue"),
    Metric("ocf_to_net_income", "Operating cash flow / net income", "ratio", True,
           "Reported operating cash flow / net income (not meaningful when net income <= 0)"),
    Metric("capex_growth", "Capex growth", "pct", None, "PP&E capex / prior-year PP&E capex - 1"),
    Metric("inventory_growth", "Inventory growth", "pct", None, "Year-end inventory / prior year-end inventory - 1"),
    Metric("inventory_turnover", "Inventory turnover", "ratio", True, "Cost of revenue / average inventory"),
    Metric("days_inventory", "Days inventory outstanding", "days", False, "365 / inventory turnover"),
]
METRICS_BY_KEY = {m.key: m for m in METRICS}
CORE_METRICS = [m.key for m in METRICS[:11]]


def _native_frame(cf: CompanyFinancials) -> pd.DataFrame:
    rows = {cy: {k: v.native for k, v in items.items()} for cy, items in cf.values.items()}
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


def _div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


def _col(df: pd.DataFrame, key: str) -> pd.Series:
    return df[key] if key in df else pd.Series(np.nan, index=df.index)


def company_metrics(cf: CompanyFinancials) -> pd.DataFrame:
    d = _native_frame(cf)
    # Growth and averages need the immediately preceding period; reindex so gaps give NaN.
    d = d.reindex(range(d.index.min(), d.index.max() + 1))
    rev, cost = _col(d, "revenue"), _col(d, "cost_of_revenue")
    ni, ocf, capex = _col(d, "net_income"), _col(d, "operating_cash_flow"), _col(d, "capex")
    assets, inv = _col(d, "total_assets"), _col(d, "inventory")
    avg_assets = (assets + assets.shift(1)) / 2
    avg_inv = (inv + inv.shift(1)) / 2

    m = pd.DataFrame(index=d.index)
    m["revenue_growth"] = _div(rev, rev.shift(1)) - 1
    m["gross_margin"] = _div(_col(d, "gross_profit"), rev)
    m["operating_margin"] = _div(_col(d, "operating_income"), rev)
    m["net_margin"] = _div(ni, rev)
    m["current_ratio"] = _div(_col(d, "current_assets"), _col(d, "current_liabilities"))
    m["liabilities_to_assets"] = _div(_col(d, "total_liabilities"), assets)
    m["roa"] = _div(ni, avg_assets)
    m["asset_turnover"] = _div(rev, avg_assets)
    m["fcf_margin"] = _div(ocf - capex, rev)
    m["capex_pct_revenue"] = _div(capex, rev)
    m["ocf_to_net_income"] = _div(ocf, ni.where(ni > 0))
    m["capex_growth"] = _div(capex, capex.shift(1)) - 1
    m["inventory_growth"] = _div(inv, inv.shift(1)) - 1
    m["inventory_turnover"] = _div(cost, avg_inv)
    m["days_inventory"] = _div(pd.Series(365.0, index=d.index), m["inventory_turnover"])

    # Helper columns used by the risk rules (not reported as metrics).
    m["_net_income"] = ni
    m["_ocf"] = ocf
    m["_fcf"] = ocf - capex
    m["_ni_change"] = ni - ni.shift(1)
    m["_ocf_change"] = ocf - ocf.shift(1)
    return m


def all_metrics(companies: list[CompanyFinancials]) -> pd.DataFrame:
    """Frame indexed by (company, comparison_year) for every downloaded period, base year included.

    The base year (the year before the analysis window) is kept so that rules for the first
    year in the window can compare against it; reports filter to the window.
    """
    frames = []
    for cf in companies:
        m = company_metrics(cf)
        m = m[m.index.isin(list(cf.periods))]
        m.index = pd.MultiIndex.from_product([[cf.company.name], m.index], names=["company", "comparison_year"])
        frames.append(m)
    return pd.concat(frames)


def displays_equal(a: float, b: float, fmt: str) -> bool:
    """True when two values look identical at report precision (no better/worse marker then)."""
    return format_value(a, fmt) == format_value(b, fmt)


def format_value(value: float, fmt: str) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    if fmt == "pct":
        return f"{value * 100:.1f}%"
    if fmt == "days":
        return f"{value:.0f} days"
    return f"{value:.2f}x"
