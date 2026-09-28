"""Transparent, rule-based risk scoring.

Each rule is a plain accounting test with a fixed threshold and point value. A
company's score for a period is the sum of the points of the rules it triggers, and
the report lists every rule with its result, so each score can be traced back to
the numbers that produced it.

Rule results:
  TRIGGERED      the test failed and the rule's points were added
  passed         the test was evaluated and passed
  informational  a peer comparison is shown but assigns no points (too few usable
                 peers, or the peers' figures are not comparable)
  not evaluated  required data was missing

These flags identify unusual financial patterns that may warrant further
investigation. They do not detect fraud or predict share prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

RISK_BANDS = [(6, "Elevated Risk"), (3, "Moderate Risk"), (0, "Lower Risk")]

RULE_FAMILIES = {
    "PROF": "Profitability rules",
    "GROW": "Growth rules",
    "CASH": "Cash-flow and earnings-quality rules",
    "LEV": "Leverage rules",
    "LIQ": "Liquidity rules",
    "INV": "Inventory rules",
}

MIN_PEERS = 3  # usable, comparable peer values required before a peer median can assign points
FCF_MATERIALITY = -0.005  # free-cash-flow margin at or below -0.50% of revenue

TRIGGERED, PASSED, INFORMATIONAL, NOT_EVALUATED = "TRIGGERED", "passed", "informational", "not evaluated"


def risk_level(score: int) -> str:
    return next(label for floor, label in RISK_BANDS if score >= floor)


@dataclass(frozen=True)
class Context:
    cur: pd.Series  # this company's metrics for the period
    prev: pd.Series  # this company's metrics for the prior period (empty if unavailable)
    peers: pd.DataFrame  # the other companies' metrics for the same comparison year
    cur_label: str = ""  # reported fiscal-year label, e.g. "FY2026"
    prev_label: str = ""


@dataclass(frozen=True)
class Rule:
    id: str
    name: str  # plain-English name shown beside the id
    category: str
    points: int
    test: str  # the rule as shown in the report
    # Returns (hit, detail); None when data is missing; (None, reason) when the test does not apply.
    check: Callable[[Context], tuple[bool | None, str] | None]
    peer_metric: str | None = None  # set for rules that compare against a peer median
    classification_sensitive: tuple[str, ...] = ()  # metrics whose absolute threshold assumes comparable classification


@dataclass(frozen=True)
class RuleResult:
    company: str
    comparison_year: int
    reported_fiscal_year: str
    period_end: str
    rule: Rule
    status: str
    detail: str
    comparability_note: str = ""

    @property
    def triggered(self) -> bool:
        return self.status == TRIGGERED

    @property
    def points(self) -> int:
        return self.rule.points if self.triggered else 0


def _na(*values) -> bool:
    return any(v is None or pd.isna(v) for v in values)


def _pp(x: float) -> str:
    return f"{x * 100:+.1f} pp"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _pct2(x: float) -> str:
    return f"{x * 100:.2f}%"


def _span(ctx: Context, prev_text: str, cur_text: str) -> str:
    """'FY2025 10.0% to FY2026 7.4%' (labels omitted when unknown)."""
    p = f"{ctx.prev_label} {prev_text}".strip()
    c = f"{ctx.cur_label} {cur_text}".strip()
    return f"{p} to {c}"


NO_PRIOR = ("Not evaluated: no prior-period value (the first year's comparison needs data from an earlier "
            "year than was downloaded)")


def _missing_prior(ctx: Context, key: str):
    """(None, reason) when this period has a value but the prior period does not; else None."""
    cur, prev = ctx.cur.get(key), ctx.prev.get(key)
    return (None, NO_PRIOR) if not _na(cur) and _na(prev) else None


def _peer_median(ctx: Context, key: str) -> float | None:
    if key not in ctx.peers or ctx.peers[key].dropna().empty:
        return None
    return float(ctx.peers[key].median())


# --- rule checks ---------------------------------------------------------------

def _margin_drop(key: str, label: str, threshold: float):
    def check(ctx: Context):
        cur, prev = ctx.cur.get(key), ctx.prev.get(key)
        if _na(cur, prev):
            return _missing_prior(ctx, key)
        change = cur - prev
        if change <= -threshold:
            return True, f"{label} fell {abs(change) * 100:.1f} percentage points ({_span(ctx, _pct(prev), _pct(cur))})"
        return False, f"{label} changed {_pp(change)} ({_span(ctx, _pct(prev), _pct(cur))})"
    return check


def _net_loss(ctx: Context):
    ni = ctx.cur.get("_net_income")
    if _na(ni):
        return None
    return ni < 0, "Reported a net loss" if ni < 0 else "Net income was positive"


def _versus_peers(key: str, label: str, threshold: float, direction: str):
    """direction 'below' flags cur <= median - threshold; 'above' flags cur >= median + threshold."""
    def check(ctx: Context):
        cur, med = ctx.cur.get(key), _peer_median(ctx, key)
        if _na(cur, med):
            return None
        gap = cur - med
        side = "above" if gap > 0 else "below"
        hit = gap <= -threshold if direction == "below" else gap >= threshold
        n = int(ctx.peers[key].notna().sum())
        return hit, (f"{label} of {_pct(cur)} is {abs(gap) * 100:.1f} pp {side} the median of {n} peer "
                     f"value{'s' if n != 1 else ''} ({_pct(med)})")
    return check


def _revenue_decline(ctx: Context):
    g = ctx.cur.get("revenue_growth")
    if _na(g):
        return None
    return g < 0, f"Revenue {'declined' if g < 0 else 'grew'} {abs(g) * 100:.1f}%"


def _revenue_slowdown(ctx: Context):
    g, g_prev = ctx.cur.get("revenue_growth"), ctx.prev.get("revenue_growth")
    if not _na(g) and _na(g_prev):
        return None, "Not evaluated: prior-period revenue growth needs two earlier periods of data"
    if _na(g, g_prev):
        return None
    slowed = g >= 0 and g - g_prev <= -0.10  # outright declines are covered by the decline rule
    return slowed, f"Revenue growth went from {_span(ctx, _pct(g_prev), _pct(g))} ({_pp(g - g_prev)})"


def _capex_outpaces_revenue(ctx: Context):
    cg, rg = ctx.cur.get("capex_growth"), ctx.cur.get("revenue_growth")
    if _na(cg, rg):
        return None
    return cg - rg >= 0.10, f"PP&E capex grew {_pct(cg)} vs revenue growth of {_pct(rg)}"


def _ocf_down_ni_up(ctx: Context):
    d_ocf, d_ni = ctx.cur.get("_ocf_change"), ctx.cur.get("_ni_change")
    if _na(d_ocf, d_ni):
        return None
    hit = d_ocf < 0 < d_ni
    return hit, (f"Reported operating cash flow {'declined' if d_ocf < 0 else 'increased'} while net income "
                 f"{'increased' if d_ni > 0 else 'declined'} ({ctx.prev_label} to {ctx.cur_label})")


def _low_cash_conversion(ctx: Context):
    ratio, ni = ctx.cur.get("ocf_to_net_income"), ctx.cur.get("_net_income")
    if not _na(ni) and ni <= 0:
        return None, "Not applicable: net income was not positive, so the cash-conversion ratio is not meaningful"
    if _na(ni, ratio):
        return None
    return ratio < 0.8, f"Reported operating cash flow was {ratio:.2f}x net income"


def _negative_fcf(ctx: Context):
    margin = ctx.cur.get("fcf_margin")
    if _na(margin):
        return None
    if margin <= FCF_MATERIALITY:
        return True, f"Free cash flow was negative: {_pct2(margin)} of revenue (threshold -0.50%)"
    if margin < 0:
        return False, (f"Free cash flow was negative ({_pct2(margin)} of revenue) but not below the -0.50% "
                       f"materiality threshold")
    return False, f"Free cash flow was positive ({_pct(margin)} of revenue)"


def _negative_fcf_two_years(ctx: Context):
    m, m_prev = ctx.cur.get("fcf_margin"), ctx.prev.get("fcf_margin")
    if _na(m, m_prev):
        return None
    hit = m <= FCF_MATERIALITY and m_prev <= FCF_MATERIALITY
    return hit, f"Free-cash-flow margin {_span(ctx, _pct2(m_prev), _pct2(m))} (threshold -0.50% in both periods)"


def _rise(key: str, label: str, threshold: float, fmt: Callable[[float], str] = _pct, unit: str = "pp"):
    def check(ctx: Context):
        cur, prev = ctx.cur.get(key), ctx.prev.get(key)
        if _na(cur, prev):
            return _missing_prior(ctx, key)
        change = cur - prev
        amount = f"{change * 100:+.1f} pp" if unit == "pp" else f"{round(change):+d} {unit}"
        return change >= threshold, f"{label} moved {amount} ({_span(ctx, fmt(prev), fmt(cur))})"
    return check


def _low_current_ratio(ctx: Context):
    cr = ctx.cur.get("current_ratio")
    if _na(cr):
        return None
    return cr < 1.0, f"Current ratio of {cr:.2f}x"


def _current_ratio_drop(ctx: Context):
    cr, prev = ctx.cur.get("current_ratio"), ctx.prev.get("current_ratio")
    if _na(cr, prev):
        return _missing_prior(ctx, "current_ratio")
    return cr - prev <= -0.20, f"Current ratio moved from {_span(ctx, f'{prev:.2f}x', f'{cr:.2f}x')}"


def _inventory_outpaces_revenue(ctx: Context):
    ig, rg = ctx.cur.get("inventory_growth"), ctx.cur.get("revenue_growth")
    if _na(ig, rg):
        return None
    return ig - rg >= 0.05, f"Inventory grew {_pct(ig)} vs revenue growth of {_pct(rg)}"


def _turnover_drop(ctx: Context):
    t, prev = ctx.cur.get("inventory_turnover"), ctx.prev.get("inventory_turnover")
    if _na(t, prev) or prev == 0:
        return _missing_prior(ctx, "inventory_turnover")
    change = t / prev - 1
    return change <= -0.10, (f"Inventory turnover moved from {_span(ctx, f'{prev:.2f}x', f'{t:.2f}x')} "
                             f"({change * 100:+.1f}%)")


# --- rule catalogue --------------------------------------------------------------

GENERAL_RULES = [
    Rule("PROF-1", "Operating margin decline", "Profitability", 2,
         "Operating margin fell by 2.0 percentage points or more versus the prior period",
         _margin_drop("operating_margin", "Operating margin", 0.02)),
    Rule("PROF-2", "Gross margin decline", "Profitability", 1,
         "Gross margin fell by 2.0 percentage points or more versus the prior period",
         _margin_drop("gross_margin", "Gross margin", 0.02)),
    Rule("PROF-3", "Net loss", "Profitability", 2, "Net loss attributable to the parent", _net_loss),
    Rule("PROF-4", "Return on assets below peers", "Profitability", 1,
         f"Return on assets is 2.0 pp or more below the peer median (requires {MIN_PEERS}+ usable peers)",
         _versus_peers("roa", "Return on assets", 0.02, "below"), peer_metric="roa"),
    Rule("GROW-1", "Revenue decline", "Growth", 2, "Revenue declined versus the prior period", _revenue_decline),
    Rule("GROW-2", "Revenue growth slowdown", "Growth", 1,
         "Revenue growth slowed by 10 pp or more (while still positive)", _revenue_slowdown),
    Rule("GROW-3", "Capex outpacing revenue", "Growth", 1,
         "PP&E capex growth exceeded revenue growth by 10 pp or more", _capex_outpaces_revenue),
    Rule("CASH-1", "Cash flow diverging from earnings", "Earnings quality", 3,
         "Reported operating cash flow declined while net income increased", _ocf_down_ni_up),
    Rule("CASH-2", "Low cash conversion", "Earnings quality", 2,
         "Reported operating cash flow below 0.8x positive net income", _low_cash_conversion,
         classification_sensitive=("ocf_to_net_income",)),
    Rule("CASH-3", "Negative free cash flow", "Cash flow", 1,
         "Free-cash-flow margin at or below -0.50% of revenue", _negative_fcf,
         classification_sensitive=("fcf_margin",)),
    Rule("CASH-4", "Negative free cash flow two periods running", "Cash flow", 1,
         "Free-cash-flow margin at or below -0.50% of revenue in this and the prior period",
         _negative_fcf_two_years, classification_sensitive=("fcf_margin",)),
    Rule("LEV-1", "Leverage above peers", "Leverage", 2,
         f"Liabilities-to-assets is 5.0 pp or more above the peer median (requires {MIN_PEERS}+ usable, "
         f"comparable peers)",
         _versus_peers("liabilities_to_assets", "Liabilities-to-assets", 0.05, "above"),
         peer_metric="liabilities_to_assets"),
    Rule("LEV-2", "Rising leverage", "Leverage", 1,
         "Liabilities-to-assets rose by 3.0 pp or more versus the prior period",
         _rise("liabilities_to_assets", "Liabilities-to-assets", 0.03)),
    Rule("LIQ-1", "Current ratio below 1.0", "Liquidity", 1, "Current ratio below 1.0x", _low_current_ratio),
    Rule("LIQ-2", "Falling current ratio", "Liquidity", 1,
         "Current ratio fell by 0.20 or more versus the prior period", _current_ratio_drop),
]

INDUSTRY_RULES = {
    "INV-1": Rule("INV-1", "Inventory outpacing sales", "Inventory", 2,
                  "Inventory growth exceeded revenue growth by 5 pp or more", _inventory_outpaces_revenue),
    "INV-2": Rule("INV-2", "Slowing inventory turnover", "Inventory", 1,
                  "Inventory turnover fell by 10% or more versus the prior period", _turnover_drop),
    "INV-3": Rule("INV-3", "Rising days of inventory", "Inventory", 1,
                  "Days inventory outstanding rose by 15 days or more",
                  _rise("days_inventory", "Days inventory outstanding", 15, lambda d: f"{d:.0f} days", "days")),
}

# Signature: (metric, companies involved) -> titles of warnings that block the comparison.
PeerGuard = Callable[[str, list[str]], list[str]]
# Signature: (metric, company) -> titles of warnings that apply to the company's metric.
MetricNotes = Callable[[str, str], list[str]]


def evaluate(metrics: pd.DataFrame, rules: list[Rule], years: range,
             labels: dict[tuple[str, int], tuple[str, str]],
             peer_guard: PeerGuard = lambda metric, companies: [],
             metric_notes: MetricNotes = lambda metric, company: []) -> list[RuleResult]:
    """Run every rule for every company in each comparison year in `years`.

    `metrics` must include the period before the first year so the first year has a prior
    period to compare against. `labels` maps (company, comparison year) to
    (reported fiscal-year label, period end).
    """
    results = []
    companies = metrics.index.get_level_values("company").unique()
    empty = pd.Series(dtype=float)
    for year in years:
        if year not in metrics.index.get_level_values("comparison_year"):
            continue
        year_slice = metrics.xs(year, level="comparison_year")
        for company in companies:
            if (company, year) not in metrics.index:
                continue
            cur_label, period_end = labels.get((company, year), ("", ""))
            prev_label = labels.get((company, year - 1), ("", ""))[0]
            prev = metrics.loc[(company, year - 1)] if (company, year - 1) in metrics.index else empty
            peers = year_slice.drop(index=company, errors="ignore")
            for rule in rules:
                status, detail, note = _run_rule(rule, metrics.loc[(company, year)], prev, peers, company,
                                                 cur_label, prev_label, peer_guard, metric_notes)
                results.append(RuleResult(company, year, cur_label, period_end, rule, status, detail, note))
    return results


def _run_rule(rule: Rule, cur: pd.Series, prev: pd.Series, peers: pd.DataFrame, company: str,
              cur_label: str, prev_label: str, peer_guard: PeerGuard, metric_notes: MetricNotes):
    note = "; ".join(t for m in rule.classification_sensitive for t in metric_notes(m, company))
    informational = ""
    if rule.peer_metric:
        usable = peers[peers[rule.peer_metric].notna()] if rule.peer_metric in peers else peers.iloc[0:0]
        blocked = peer_guard(rule.peer_metric, [company, *usable.index])
        if blocked:
            informational = f"figures not comparable ({'; '.join(blocked)})"
        elif len(usable) < MIN_PEERS:
            informational = f"only {len(usable)} usable peer value(s); at least {MIN_PEERS} are required for points"
        peers = usable
    outcome = rule.check(Context(cur, prev, peers, cur_label, prev_label))
    if outcome is None:
        return NOT_EVALUATED, "Not evaluated: required data missing", note
    if outcome[0] is None:
        return NOT_EVALUATED, outcome[1], note
    hit, detail = bool(outcome[0]), outcome[1]
    if informational:
        return INFORMATIONAL, f"{detail} - informational only, no points: {informational}", note
    if note:
        detail = f"{detail} (comparability warning: {note})"
    return (TRIGGERED if hit else PASSED), detail, note


def results_frame(results: list[RuleResult]) -> pd.DataFrame:
    return pd.DataFrame([{
        "company": r.company,
        "reported_fiscal_year": r.reported_fiscal_year,
        "period_end": r.period_end,
        "comparison_year": r.comparison_year,
        "rule_id": r.rule.id,
        "rule_name": r.rule.name,
        "category": r.rule.category,
        "rule": r.rule.test,
        "result": r.status,
        "points": r.points,
        "max_points": r.rule.points,
        "detail": r.detail,
        "comparability_note": r.comparability_note,
    } for r in results])


def scores(results: list[RuleResult]) -> pd.DataFrame:
    """Score per company and comparison year, with the reported fiscal-year label and risk band."""
    df = results_frame(results)
    out = (df.groupby(["company", "comparison_year", "reported_fiscal_year", "period_end"])["points"].sum()
           .rename("score").reset_index())
    out["risk_level"] = out["score"].map(risk_level)
    return out


def stability_notes(metrics: pd.DataFrame, results: list[RuleResult], company: str, year: int) -> list[str]:
    """Plain-language observations for areas where no rule fired."""
    fired = {r.rule.category for r in results if r.company == company and r.comparison_year == year and r.triggered}
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
        notes.append(f"Reported operating cash flow was {cur['ocf_to_net_income']:.2f}x net income.")
    fcf = cur.get("fcf_margin")
    if not _na(fcf) and FCF_MATERIALITY < fcf < 0:
        notes.append(f"Free cash flow was slightly negative ({_pct2(fcf)} of revenue), within the -0.50% threshold.")
    return notes
