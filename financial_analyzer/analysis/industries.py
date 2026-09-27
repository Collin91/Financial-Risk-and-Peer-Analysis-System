"""Industry profiles: default peer sets, industry-specific metrics and rules, and caveats.

The general metrics and rules always run; a profile only adds to them.
"""

from __future__ import annotations

from dataclasses import dataclass

from financial_analyzer.analysis.metrics import CORE_METRICS
from financial_analyzer.analysis.risk import GENERAL_RULES, INDUSTRY_RULES, Rule


@dataclass(frozen=True)
class IndustryProfile:
    name: str
    default_companies: tuple[str, ...]  # target first, then default peers
    suggested_companies: tuple[str, ...] = ()  # offered as numbered choices in the CLI
    extra_metrics: tuple[str, ...] = ()
    extra_rules: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def metric_keys(self) -> list[str]:
        return CORE_METRICS + list(self.extra_metrics)

    @property
    def rules(self) -> list[Rule]:
        return GENERAL_RULES + [INDUSTRY_RULES[r] for r in self.extra_rules]


PROFILES = {
    "automotive": IndustryProfile(
        name="Automotive",
        default_companies=("Tesla", "Ford", "Toyota"),
        suggested_companies=("Tesla", "Ford", "Toyota", "General Motors", "Honda", "Stellantis"),
        extra_metrics=("days_inventory",),
        extra_rules=("INV-3",),
        notes=(
            "Toyota's fiscal year ends on 31 March; Tesla's and Ford's end on 31 December. Toyota FY2026 (year "
            "ended March 31, 2026) is compared with Tesla's and Ford's FY2025 in comparison year 2025.",
            "Balance-sheet comparisons between companies are three months apart when their fiscal years end on "
            "different dates.",
        ),
    ),
    "retail": IndustryProfile(
        name="Retail",
        default_companies=("Walmart", "Target", "Costco"),
        suggested_companies=("Walmart", "Target", "Costco", "Home Depot", "Lowe's", "Kroger"),
        extra_metrics=("inventory_growth", "inventory_turnover", "days_inventory"),
        extra_rules=("INV-1", "INV-2", "INV-3"),
        notes=(
            "Retailers' fiscal years end in late January / early February (Walmart, Target) or late August / "
            "early September (Costco). Each company's own fiscal-year label is shown; years ending January-May are "
            "placed in the prior comparison year.",
            "Costco's membership fees are included in revenue but carry no cost of goods, which lifts its gross margin "
            "above what merchandise sales alone would produce.",
        ),
    ),
    "general": IndustryProfile(name="Other", default_companies=()),
}


def get_profile(industry: str) -> IndustryProfile:
    try:
        key = industry.strip().lower()
        return PROFILES["general" if key == "other" else key]
    except KeyError:
        raise ValueError(f"Unknown industry '{industry}'. Choose from: {', '.join(p.name for p in PROFILES.values())}")
