"""Transparent, rule-based risk scoring.

Each rule is a plain accounting test with a fixed threshold and point value. A
company's score for a year is the sum of the points of the rules it triggers, and
the report lists every rule with its result, so each score can be traced back to
the numbers that produced it.

These flags identify unusual financial patterns that may warrant further
investigation. They do not detect fraud or predict share prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

RISK_BANDS = [(6, "Elevated Risk"), (3, "Moderate Risk"), (0, "Lower Risk")]


def risk_level(score: int) -> str:
    return next(label for floor, label in RISK_BANDS if score >= floor)


@dataclass(frozen=True)
class Context:
    cur: pd.Series  # this company's metrics for the year
    prev: pd.Series  # this company's metrics for the prior year (all NaN if unavailable)
    peers: pd.DataFrame  # the other companies' metrics for the same year


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    points: int
    test: str  # the rule as shown in the report
    check: Callable[[Context], tuple[bool, str] | None]  # None = not enough data


@dataclass(frozen=True)
class RuleResult:
    company: str
    fiscal_year: int
    rule: Rule
    triggered: bool | None
    detail: str

    @property
    def points(self) -> int:
        return self.rule.points if self.triggered else 0


def _na(*values) -> bool:
    return any(v is None or pd.isna(v) for v in values)


def _pp(x: float) -> str:
    return f"{x * 100:+.1f} pp"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _peer_median(ctx: Context, key: str) -> float | None:
    if key not in ctx.peers or ctx.peers[key].dropna().empty:
        return None
    return float(ctx.peers[key].median())


# --- rule checks ---------------------------------------------------------------

def _margin_drop(key: str, label: str, threshold: float):
    def check(ctx: Context):
        cur, prev = ctx.cur.get(key), ctx.prev.get(key)
        if _na(cur, prev):
            return None
        change = cur - prev
        if change <= -threshold:
            return True, f"{label} fell {abs(change) * 100:.1f} percentage points ({_pct(prev)} to {_pct(cur)})"
        return False, f"{label} changed {_pp(change)} ({_pct(prev)} to {_pct(cur)})"
    return check


def _net_loss(ctx: Context):
    ni = ctx.cur.get("_net_income")
    if _na(ni):
        return None
    return ni < 0, "Reported a net loss" if ni < 0 else "Net income was positive"


def _below_peers(key: str, label: str, threshold: float):
    def check(ctx: Context):
        cur, med = ctx.cur.get(key), _peer_median(ctx, key)
        if _na(cur, med):
            return None
        gap = cur - med
        verdict = "below" if gap < 0 else "above"
        return gap <= -threshold, f"{label} of {_pct(cur)} is {abs(gap) * 100:.1f} pp {verdict} the peer median ({_pct(med)})"
    return check


def _above_peers(key: str, label: str, threshold: float):
    def check(ctx: Context):
        cur, med = ctx.cur.get(key), _peer_median(ctx, key)
        if _na(cur, med):
            return None
        gap = cur - med
        verdict = "above" if gap > 0 else "below"
        return gap >= threshold, f"{label} of {_pct(cur)} is {abs(gap) * 100:.1f} pp {verdict} the peer median ({_pct(med)})"
    return check


def _revenue_decline(ctx: Context):
    g = ctx.cur.get("revenue_growth")
    if _na(g):
        return None
    return g < 0, f"Revenue {'declined' if g < 0 else 'grew'} {abs(g) * 100:.1f}%"


def _revenue_slowdown(ctx: Context):
    g, g_prev = ctx.cur.get("revenue_growth"), ctx.prev.get("revenue_growth")
    if _na(g, g_prev):
        return None
    slowed = g >= 0 and g - g_prev <= -0.10  # outright declines are covered by the decline rule
    return slowed, f"Revenue growth went from {_pct(g_prev)} to {_pct(g)} ({_pp(g - g_prev)})"


def _capex_outpaces_revenue(ctx: Context):
    cg, rg = ctx.cur.get("capex_growth"), ctx.cur.get("revenue_growth")
    if _na(cg, rg):
        return None
    return cg - rg >= 0.10, f"Capex grew {_pct(cg)} vs revenue growth of {_pct(rg)}"


def _ocf_down_ni_up(ctx: Context):
    d_ocf, d_ni = ctx.cur.get("_ocf_change"), ctx.cur.get("_ni_change")
    if _na(d_ocf, d_ni):
        return None
    hit = d_ocf < 0 < d_ni
    return hit, (f"Operating cash flow {'declined' if d_ocf < 0 else 'increased'} while net income "
                 f"{'increased' if d_ni > 0 else 'declined'}")


def _low_cash_conversion(ctx: Context):
    ratio, ni = ctx.cur.get("ocf_to_net_income"), ctx.cur.get("_net_income")
    if _na(ni) or ni <= 0:
        return None  # ratio is not meaningful for a loss year
    if _na(ratio):
        return None
    return ratio < 0.8, f"Operating cash flow was {ratio:.2f}x net income"


def _negative_fcf(ctx: Context):
    fcf = ctx.cur.get("_fcf")
    if _na(fcf):
        return None
    return fcf < 0, f"Free cash flow margin was {_pct(ctx.cur.get('fcf_margin'))}"


def _negative_fcf_two_years(ctx: Context):
    fcf, fcf_prev = ctx.cur.get("_fcf"), ctx.prev.get("_fcf")
    if _na(fcf, fcf_prev):
        return None
    hit = fcf < 0 and fcf_prev < 0
    return hit, "Free cash flow negative in both this and the prior year" if hit else "Not negative in consecutive years"


def _rise(key: str, label: str, threshold: float, fmt: Callable[[float], str] = _pct, unit: str = "pp"):
    def check(ctx: Context):
        cur, prev = ctx.cur.get(key), ctx.prev.get(key)
        if _na(cur, prev):
            return None
        change = cur - prev
        amount = f"{change * 100:+.1f} pp" if unit == "pp" else f"{round(change):+d} {unit}"
        return change >= threshold, f"{label} moved {amount} ({fmt(prev)} to {fmt(cur)})"
    return check


def _low_current_ratio(ctx: Context):
    cr = ctx.cur.get("current_ratio")
    if _na(cr):
        return None
    return cr < 1.0, f"Current ratio of {cr:.2f}x"


def _current_ratio_drop(ctx: Context):
    cr, prev = ctx.cur.get("current_ratio"), ctx.prev.get("current_ratio")
    if _na(cr, prev):
        return None
    return cr - prev <= -0.20, f"Current ratio moved from {prev:.2f}x to {cr:.2f}x"


def _inventory_outpaces_revenue(ctx: Context):
    ig, rg = ctx.cur.get("inventory_growth"), ctx.cur.get("revenue_growth")
    if _na(ig, rg):
        return None
    return ig - rg >= 0.05, f"Inventory grew {_pct(ig)} vs revenue growth of {_pct(rg)}"


def _turnover_drop(ctx: Context):
    t, prev = ctx.cur.get("inventory_turnover"), ctx.prev.get("inventory_turnover")
    if _na(t, prev) or prev == 0:
        return None
    change = t / prev - 1
    return change <= -0.10, f"Inventory turnover moved from {prev:.2f}x to {t:.2f}x ({change * 100:+.1f}%)"


# --- rule catalogue --------------------------------------------------------------

GENERAL_RULES = [
    Rule("PROF-1", "Profitability", 2, "Operating margin fell by 2.0 percentage points or more year over year",
         _margin_drop("operating_margin", "Operating margin", 0.02)),
    Rule("PROF-2", "Profitability", 1, "Gross margin fell by 2.0 percentage points or more year over year",
         _margin_drop("gross_margin", "Gross margin", 0.02)),
    Rule("PROF-3", "Profitability", 2, "Net loss attributable to the parent", _net_loss),
    Rule("PROF-4", "Profitability", 1, "Return on assets is 2.0 pp or more below the peer median",
         _below_peers("roa", "Return on assets", 0.02)),
    Rule("GROW-1", "Growth", 2, "Revenue declined year over year", _revenue_decline),
    Rule("GROW-2", "Growth", 1, "Revenue growth slowed by 10 pp or more (while still positive)", _revenue_slowdown),
    Rule("GROW-3", "Growth", 1, "Capex growth exceeded revenue growth by 10 pp or more", _capex_outpaces_revenue),
    Rule("CASH-1", "Earnings quality", 3, "Operating cash flow declined while net income increased", _ocf_down_ni_up),
    Rule("CASH-2", "Earnings quality", 2, "Operating cash flow below 0.8x positive net income", _low_cash_conversion),
    Rule("CASH-3", "Cash flow", 1, "Negative free cash flow (operating cash flow - capex)", _negative_fcf),
    Rule("CASH-4", "Cash flow", 1, "Negative free cash flow two years in a row", _negative_fcf_two_years),
    Rule("LEV-1", "Leverage", 2, "Debt-to-assets is 5.0 pp or more above the peer median",
         _above_peers("debt_to_assets", "Debt-to-assets", 0.05)),
    Rule("LEV-2", "Leverage", 1, "Debt-to-assets rose by 3.0 pp or more year over year",
         _rise("debt_to_assets", "Debt-to-assets", 0.03)),
    Rule("LIQ-1", "Liquidity", 1, "Current ratio below 1.0x", _low_current_ratio),
    Rule("LIQ-2", "Liquidity", 1, "Current ratio fell by 0.20 or more year over year", _current_ratio_drop),
]

INDUSTRY_RULES = {
    "INV-1": Rule("INV-1", "Inventory", 2, "Inventory growth exceeded revenue growth by 5 pp or more",
                  _inventory_outpaces_revenue),
    "INV-2": Rule("INV-2", "Inventory", 1, "Inventory turnover fell by 10% or more year over year", _turnover_drop),
    "INV-3": Rule("INV-3", "Inventory", 1, "Days inventory outstanding rose by 15 days or more",
                  _rise("days_inventory", "Days inventory outstanding", 15, lambda d: f"{d:.0f} days", "days")),
}


def evaluate(metrics: pd.DataFrame, rules: list[Rule]) -> list[RuleResult]:
    """Run every rule for every company-year that has a prior year to compare against."""
    results = []
    companies = metrics.index.get_level_values("company").unique()
    years = sorted(metrics.index.get_level_values("fiscal_year").unique())
    empty = pd.Series(dtype=float)
    for year in years:
        year_slice = metrics.xs(year, level="fiscal_year")
        for company in companies:
            if (company, year) not in metrics.index:
                continue
            prev = metrics.loc[(company, year - 1)] if (company, year - 1) in metrics.index else empty
            ctx = Context(metrics.loc[(company, year)], prev, year_slice.drop(index=company, errors="ignore"))
            for rule in rules:
                outcome = rule.check(ctx)
                if outcome is None:
                    results.append(RuleResult(company, year, rule, None, "Not enough data to evaluate"))
                else:
                    results.append(RuleResult(company, year, rule, bool(outcome[0]), outcome[1]))
    return results


def results_frame(results: list[RuleResult]) -> pd.DataFrame:
    return pd.DataFrame([{
        "company": r.company,
        "fiscal_year": r.fiscal_year,
        "rule_id": r.rule.id,
        "category": r.rule.category,
        "rule": r.rule.test,
        "result": {True: "TRIGGERED", False: "passed", None: "n/a"}[r.triggered],
        "points": r.points,
        "max_points": r.rule.points,
        "detail": r.detail,
    } for r in results])


def scores(results: list[RuleResult]) -> pd.DataFrame:
    """Score per company-year with the risk band."""
    df = results_frame(results)
    out = df.groupby(["company", "fiscal_year"])["points"].sum().rename("score").reset_index()
    out["risk_level"] = out["score"].map(risk_level)
    return out


def stability_notes(metrics: pd.DataFrame, results: list[RuleResult], company: str, year: int) -> list[str]:
    """Plain-language observations for areas where no rule fired."""
    fired = {r.rule.category for r in results if r.company == company and r.fiscal_year == year and r.triggered}
    if (company, year) not in metrics.index or (company, year - 1) not in metrics.index:
        return []
    cur, prev = metrics.loc[(company, year)], metrics.loc[(company, year - 1)]
    notes = []
    stable = {}  # area -> evidence
    if "Profitability" not in fired and not _na(cur["operating_margin"], prev["operating_margin"]):
        stable["Profitability"] = f"operating margin {_pp(cur['operating_margin'] - prev['operating_margin'])}"
    if "Liquidity" not in fired and not _na(cur["current_ratio"], prev["current_ratio"]):
        stable["Liquidity"] = f"current ratio {cur['current_ratio'] - prev['current_ratio']:+.2f}"
    if len(stable) == 2:
        notes.append(f"Profitability and liquidity remained relatively stable ({'; '.join(stable.values())}).")
    elif stable:
        area, evidence = next(iter(stable.items()))
        notes.append(f"{area} remained relatively stable ({evidence}).")
    if not fired & {"Earnings quality", "Cash flow"} and not _na(cur.get("ocf_to_net_income")):
        notes.append(f"Cash flow supports reported earnings (operating cash flow {cur['ocf_to_net_income']:.2f}x net income).")
    return notes
