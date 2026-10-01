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
    "technology": IndustryProfile(
        name="Technology",
        default_companies=("Apple", "Microsoft", "Alphabet", "Meta"),
        suggested_companies=("Apple", "Microsoft", "Alphabet", "Meta", "Nvidia", "Oracle"),
        notes=(
            "Large share buybacks shrink shareholders' equity, which raises liabilities-to-assets without any new "
            "borrowing (Apple is the clearest case). Read leverage flags together with the cash-flow figures.",
            "Data-center spending has made capex unusually heavy for some of these companies; capex-growth flags "
            "may reflect a deliberate investment cycle rather than strain.",
        ),
    ),
    "pharmaceuticals": IndustryProfile(
        name="Pharmaceuticals",
        default_companies=("Pfizer", "Merck", "Johnson & Johnson", "Eli Lilly"),
        suggested_companies=("Pfizer", "Merck", "Johnson & Johnson", "Eli Lilly", "AbbVie", "Bristol-Myers Squibb"),
        notes=(
            "Acquisitions are often followed by large write-offs of acquired research (in-process R&D), which can "
            "produce a one-year loss or margin drop that says little about the underlying business.",
            "Revenue can fall sharply when a major drug loses patent protection; a revenue-decline flag is worth "
            "checking against the company's patent calendar.",
            "Most large drugmakers (Pfizer, Merck, Johnson & Johnson, Eli Lilly, Bristol-Myers Squibb) don't report "
            "an operating-income line: impairments and other operating items sit in 'other (income) deductions' "
            "together with interest. Operating margin is left blank rather than estimated; compare net margin.",
        ),
    ),
    "apparel": IndustryProfile(
        name="Apparel & Footwear",
        default_companies=("Nike", "Under Armour", "Lululemon", "Deckers"),
        suggested_companies=("Nike", "Under Armour", "Lululemon", "Deckers", "VF Corp", "Columbia Sportswear",
                             "On Holding"),
        extra_metrics=("inventory_growth", "inventory_turnover", "days_inventory"),
        extra_rules=("INV-1", "INV-2", "INV-3"),
        notes=(
            "Fiscal years end in different months (Nike in May, Deckers and Under Armour in March, Lululemon in "
            "January / February). Each company keeps its own fiscal-year label.",
            "On Holding reports under IFRS in Swiss francs; ratios use its own currency and dollar amounts use "
            "Federal Reserve exchange rates.",
        ),
    ),
    "consumer goods": IndustryProfile(
        name="Consumer Goods",
        default_companies=("Procter & Gamble", "Colgate-Palmolive", "Kimberly-Clark", "Coca-Cola"),
        suggested_companies=("Procter & Gamble", "Colgate-Palmolive", "Kimberly-Clark", "Coca-Cola", "PepsiCo",
                             "Kraft Heinz"),
        extra_metrics=("inventory_growth", "inventory_turnover", "days_inventory"),
        extra_rules=("INV-1", "INV-2", "INV-3"),
        notes=(
            "Coca-Cola sells mostly concentrate to independent bottlers, while PepsiCo bottles and distributes much "
            "of its own product; their margins and asset intensity differ by business model, not by risk.",
            "Brand write-downs (goodwill and intangible impairments) can cause one-year losses, as at Kraft Heinz.",
        ),
    ),
    "general": IndustryProfile(name="Other", default_companies=()),
}


def get_profile(industry: str) -> IndustryProfile:
    try:
        key = industry.strip().lower()
        aliases = {"other": "general", "tech": "technology", "pharma": "pharmaceuticals",
                   "apparel & footwear": "apparel", "footwear": "apparel", "consumer": "consumer goods"}
        return PROFILES[aliases.get(key, key)]
    except KeyError:
        raise ValueError(f"Unknown industry '{industry}'. Choose from: {', '.join(p.name for p in PROFILES.values())}")
