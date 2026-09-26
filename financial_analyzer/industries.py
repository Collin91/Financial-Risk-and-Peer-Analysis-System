"""Industry profiles: default peer sets, industry-specific metrics and rules, and caveats.

The general metrics and rules always run; a profile only adds to them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .metrics import CORE_METRICS
from .risk import GENERAL_RULES, INDUSTRY_RULES, Rule


@dataclass(frozen=True)
class IndustryProfile:
    name: str
    default_companies: tuple[str, ...]
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
        extra_metrics=("days_inventory",),
        extra_rules=("INV-3",),
        notes=(
            "Ford and Toyota consolidate captive finance arms (Ford Credit, Toyota Financial Services) whose "
            "loan books inflate total assets and liabilities. Debt-to-assets, asset turnover and ROA are therefore "
            "not directly comparable with a manufacturer that has no large finance subsidiary.",
            "Ford's cost of sales excludes Ford Credit interest expense, while Toyota's cost of revenue includes the "
            "cost of financing operations; gross margins are indicative rather than strictly comparable.",
            "Capital expenditures exclude vehicles purchased for operating leases where the filer reports them "
            "separately (Toyota: 'equipment leased to others').",
        ),
    ),
    "retail": IndustryProfile(
        name="Retail",
        default_companies=("Walmart", "Target", "Costco"),
        extra_metrics=("inventory_growth", "inventory_turnover", "days_inventory"),
        extra_rules=("INV-1", "INV-2", "INV-3"),
        notes=(
            "Retailers' fiscal years end in late January / early February (Walmart, Target) or late August / "
            "early September (Costco); years ending January-May are labelled with the prior calendar year.",
            "Costco's membership fees are included in revenue but carry no cost of goods, which lifts its gross margin above "
            "what merchandise sales alone would produce.",
        ),
    ),
    "general": IndustryProfile(name="General", default_companies=()),
}


def get_profile(industry: str) -> IndustryProfile:
    try:
        return PROFILES[industry.strip().lower()]
    except KeyError:
        raise ValueError(f"Unknown industry '{industry}'. Choose from: {', '.join(p.name for p in PROFILES.values())}")
