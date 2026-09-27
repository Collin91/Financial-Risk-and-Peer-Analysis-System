"""Data-comparability checks across the companies being compared.

Reported figures are never adjusted here. Each check produces a warning that is shown
in the reports; warnings marked `suppresses_peer_points` also stop peer-based risk
rules on the affected metrics from assigning points (the comparison is still shown,
labelled informational). Rules that compare a company only with its own prior years
are unaffected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from financial_analyzer.data.standardize import OCF_RECEIVABLES_MATERIALITY, CompanyFinancials


@dataclass(frozen=True)
class ComparabilityWarning:
    key: str
    title: str
    metrics: tuple[str, ...]  # metric keys whose peer comparison is affected
    companies: tuple[str, ...]  # companies whose figures cause the difference
    message: str  # full explanation
    suppresses_peer_points: bool
    summary: str = ""  # one plain-language sentence for the summary page


def _largest_number(text: str) -> float:
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    return max(numbers, default=0.0)


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _ocf_classification(financials: list[CompanyFinancials], years: range) -> ComparabilityWarning | None:
    flagged: dict[str, list[str]] = {}
    for cf in financials:
        for cy in years:
            adj = cf.support.get(cy, {}).get("fin_receivables_in_ocf")
            ocf = cf.values.get(cy, {}).get("operating_cash_flow")
            if adj is None or ocf is None or not ocf.native:
                continue
            share = abs(adj.native) / abs(ocf.native)
            if share >= OCF_RECEIVABLES_MATERIALITY:
                flagged.setdefault(cf.company.name, []).append(
                    f"{cf.periods[cy].label}: {share:.0%} of reported operating cash flow")
    others = [cf for cf in financials if cf.company.name not in flagged]
    if not flagged or not others:
        return None
    standards = {cf.company.name: cf.standard for cf in financials}
    flagged_text = "; ".join(f"{name} ({standards[name]}) - {', '.join(details)}"
                             for name, details in flagged.items())
    other_text = _join([f"{cf.company.name} ({cf.standard})" for cf in others])
    return ComparabilityWarning(
        key="ocf_classification",
        title="Operating cash flow classification differs",
        metrics=("operating_cash_flow", "ocf_to_net_income", "fcf_margin"),
        companies=tuple(flagged),
        message=(
            f"Changes in finance receivables (the financial-services loan book) are included within operating "
            f"cash flow by {flagged_text}. {other_text} do not report a comparable operating-activity adjustment; "
            f"under their U.S. GAAP presentation, purchases and collections of finance receivables are generally "
            f"classified in investing activities. Operating cash flow, operating cash flow / net income and "
            f"free-cash-flow margin for {_join(list(flagged))} may therefore not be directly comparable with peers. "
            f"Reported figures are shown unadjusted; no adjusted operating cash flow is calculated, because a "
            f"validated reconciliation for every company is not available."),
        suppresses_peer_points=True,
        summary=(f"{_join(list(flagged))}'s operating cash flow includes changes in its finance receivables, so its "
                 f"cash-flow ratios are not directly comparable with those of {_join([cf.company.name for cf in others])}."),
    )


def _captive_finance(financials: list[CompanyFinancials]) -> list[ComparabilityWarning]:
    captive = [cf for cf in financials if cf.company.captive_finance]
    if not captive:
        return []
    names = [cf.company.name for cf in financials]
    arms = _join([f"{cf.company.name} ({cf.company.captive_finance})" for cf in captive])
    derived = [cf.company.name for cf in financials
               if any(v.get("cost_of_revenue") and v["cost_of_revenue"].source.startswith("Derived: ifrs")
                      for v in cf.values.values())]
    derived_text = (f" {_join(derived)}'s cost of revenue is derived as total operating expenses minus SG&A, "
                    f"so it includes the cost of financing operations." if derived else "")
    warnings = [ComparabilityWarning(
        key="gross_margin_definition",
        title="Consolidated gross margins are not perfectly comparable",
        metrics=("gross_margin",),
        companies=tuple(names),
        message=(
            f"{_join(names)} include financing, automotive, energy, leasing and service activities differently in "
            f"consolidated revenue and cost of revenue. Captive-finance operations: {arms}.{derived_text} Each "
            f"company's reported classification is preserved (no financing costs are moved into or out of cost of "
            f"revenue), so the figures are consolidated gross margins, not automotive gross margins. Peer-based "
            f"gross-margin comparisons are informational and assign no risk points."),
        suppresses_peer_points=True,
        summary=("Gross margins are consolidated and each company classifies financing and other costs differently, "
                 "so they are compared for context only."),
    )]
    non_captive = [cf.company.name for cf in financials if not cf.company.captive_finance]
    if non_captive:
        warnings.append(ComparabilityWarning(
            key="captive_finance_leverage",
            title="Consolidated leverage mixes captive-finance and non-finance business models",
            metrics=("liabilities_to_assets",),
            companies=tuple(names),
            message=(
                f"{arms} consolidate{'' if len(captive) > 1 else 's'} material captive-finance operations whose loan and lease books add large "
                f"liabilities and assets; {_join(non_captive)} ha{'s' if len(non_captive) == 1 else 've'} no "
                f"comparable financing business. Consolidated liabilities-to-assets ratios are shown but the "
                f"peer-comparison leverage rule (LEV-1) assigns no points. Rules that compare each company with "
                f"its own prior years (LEV-2) still apply."),
            suppresses_peer_points=True,
            summary=(f"{_join([cf.company.name for cf in captive])} carry large customer-loan books, so leverage is "
                     f"not scored against {_join(non_captive)}."),
        ))
    return warnings


def _capex_scope(financials: list[CompanyFinancials], years: range) -> ComparabilityWarning | None:
    lines = []
    for cf in financials:
        # One entry per concept; when the note varies by period (e.g. the intangibles share), keep the
        # least favourable one, i.e. the highest share.
        notes_by_source: dict[str, str] = {}
        for cy, v in cf.values.items():
            if cy in years and "capex" in v:
                src, note = v["capex"].source, v["capex"].note
                notes_by_source[src] = max(notes_by_source.get(src, note), note, key=_largest_number)
        missing = [cf.periods[cy].label for cy in years if cy in cf.values and "capex" not in cf.values[cy]]
        text = "; ".join(f"{src} ({note})" for src, note in sorted(notes_by_source.items())) or "not available"
        if missing:
            text += f"; missing for {', '.join(missing)}"
        lines.append(f"{cf.company.name}: {text}")
    standards = {cf.standard for cf in financials}
    software = (" Under IFRS, software is generally an intangible asset and is excluded, whereas U.S. GAAP filers "
                "often capitalize software within PP&E, so a small scope difference remains."
                if len(standards) > 1 else "")
    return ComparabilityWarning(
        key="capex_scope",
        title="Capital expenditure definition",
        metrics=("capex_pct_revenue", "capex_growth", "fcf_margin"),
        companies=tuple(cf.company.name for cf in financials),
        message=("Capex is cash paid for purchases of property, plant and equipment for every company; acquisitions, "
                 "finance receivables, investments, intangible assets and vehicles bought for leasing to customers "
                 "are excluded. Concepts used - " + " | ".join(lines) + "." + software),
        suppresses_peer_points=False,
        summary="Capex means cash spent on property, plant and equipment for every company.",
    )


def assess(financials: list[CompanyFinancials], years: range) -> list[ComparabilityWarning]:
    warnings = [w for w in (_ocf_classification(financials, years),) if w]
    warnings += _captive_finance(financials)
    capex = _capex_scope(financials, years)
    if capex:
        warnings.append(capex)
    return warnings


def peer_comparison_blocked(warnings: list[ComparabilityWarning], metric: str, companies: list[str]) -> list[str]:
    """Titles of warnings that make a peer comparison of `metric` among `companies` non-comparable."""
    return [w.title for w in warnings
            if w.suppresses_peer_points and metric in w.metrics and set(w.companies) & set(companies)]
