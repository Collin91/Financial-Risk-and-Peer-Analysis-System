"""End-to-end pipeline: download -> standardize -> metrics -> comparison -> risk flags."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import comparability, risk, xbrl
from . import companies as companies_mod
from .industries import IndustryProfile
from .metrics import METRICS_BY_KEY, all_metrics, displays_equal
from .standardize import CompanyFinancials, Period, long_date, period_frame, standardize, to_frames

PERIOD_DISCLOSURE = (
    "Peer comparisons align periods by the calendar year containing most of each company's fiscal period. "
    "Reported fiscal-year labels and period-end dates are preserved because company fiscal years do not end on "
    "the same date."
)


@dataclass
class AnalysisResult:
    profile: IndustryProfile
    target: str
    company_names: list[str]
    first_year: int  # comparison years
    last_year: int
    financials: list[CompanyFinancials]
    periods: pd.DataFrame  # company x comparison year: reported fiscal year, period dates
    cleaned: pd.DataFrame  # USD millions, one row per company-period (base year flagged)
    lineage: pd.DataFrame
    metrics_all: pd.DataFrame  # indexed by (company, comparison_year), base year included
    comparability: list[comparability.ComparabilityWarning]
    rule_results: list[risk.RuleResult]
    scores: pd.DataFrame
    # Filled by the optional SEC event-context module; never used in calculations or scores.
    events_run: bool = False
    event_changes: list = field(default_factory=list)
    events: list = field(default_factory=list)
    event_errors: list[str] = field(default_factory=list)

    @property
    def years(self) -> range:
        return range(self.first_year, self.last_year + 1)

    @property
    def metrics(self) -> pd.DataFrame:
        """Metrics for the analysis window only."""
        cy = self.metrics_all.index.get_level_values("comparison_year")
        return self.metrics_all[(cy >= self.first_year) & (cy <= self.last_year)]

    @property
    def latest_year(self) -> int:
        return int(self.metrics.index.get_level_values("comparison_year").max())

    def period(self, company: str, year: int) -> Period | None:
        for cf in self.financials:
            if cf.company.name == company:
                return cf.periods.get(year)
        return None

    def period_label(self, company: str, year: int, with_date: bool = True) -> str:
        """'FY2026 (year ended March 31, 2026)' or 'FY2026'."""
        p = self.period(company, year)
        if p is None:
            return f"comparison year {year}: not available"
        return f"{p.label} (year ended {long_date(p.end)})" if with_date else p.label

    @property
    def warnings(self) -> list[str]:
        return [f"{cf.company.name}: {w}" for cf in self.financials for w in cf.warnings]

    def blocked(self, metric: str, companies: list[str]) -> list[str]:
        return comparability.peer_comparison_blocked(self.comparability, metric, companies)

    def peer_comparison(self, year: int) -> pd.DataFrame:
        """Metrics (rows) x companies (columns) for one comparison year, plus the peer median."""
        table = self.metrics.xs(year, level="comparison_year")[self.profile.metric_keys].T
        table = table[[c for c in self.company_names if c in table.columns]]
        table["Peer median (excl. target)"] = table.drop(columns=[self.target], errors="ignore").median(axis=1)
        return table

    def peer_marker(self, metric_key: str, year: int) -> str | None:
        """'better' / 'worse' / None for the target against its peer median (None if not comparable)."""
        metric = METRICS_BY_KEY[metric_key]
        table = self.peer_comparison(year)
        tv, med = table.loc[metric_key].get(self.target), table.loc[metric_key, "Peer median (excl. target)"]
        if metric.higher_is_better is None or pd.isna(tv) or pd.isna(med) or displays_equal(tv, med, metric.fmt):
            return None
        if self.blocked(metric_key, self.company_names):
            return None
        return "better" if (tv > med) == metric.higher_is_better else "worse"

    def target_vs_history(self) -> pd.DataFrame:
        """Target's latest period against its own average over the earlier periods in the window."""
        m = self.metrics.xs(self.target, level="company")[self.profile.metric_keys]
        latest = self.latest_year
        history = m[m.index < latest]
        return pd.DataFrame({
            "latest": m.loc[latest] if latest in m.index else pd.Series(dtype=float),
            "prior_average": history.mean(),
            "prior_min": history.min(),
            "prior_max": history.max(),
        })


def run(target: str, peers: list[str], profile: IndustryProfile, first_year: int, last_year: int,
        progress=print) -> AnalysisResult:
    """first_year / last_year are comparison years (see xbrl.comparison_year)."""
    resolved = [companies_mod.resolve(q) for q in [target, *peers]]
    financials = []
    for company in resolved:
        progress(f"Downloading annual reports for {company.name} ({company.ticker}, CIK {company.cik})...")
        # One extra period back so the first year in the window has growth rates, averages and a prior period.
        filings = xbrl.annual_filings(company.cik, first_year - 1, last_year)
        if not filings:
            raise RuntimeError(f"No 10-K/20-F filings found for {company.name} in comparison years "
                               f"{first_year - 1}-{last_year}")
        instances = [xbrl.parse_instance(f) for f in filings]
        cf = standardize(company, instances, first_year - 1, last_year, base_years=(first_year - 1,))
        progress("  " + ", ".join(f"{f.form} {cf.periods[f.comparison_year].label if f.comparison_year in cf.periods else '?'}"
                                  for f in filings))
        financials.append(cf)

    years = range(first_year, last_year + 1)
    cleaned, lineage = to_frames(financials)
    metrics_all = all_metrics(financials)
    warnings = comparability.assess(financials, years)
    labels = {(cf.company.name, cy): (p.label, p.end.isoformat()) for cf in financials for cy, p in cf.periods.items()}

    def peer_guard(metric: str, names: list[str]) -> list[str]:
        return comparability.peer_comparison_blocked(warnings, metric, names)

    def metric_notes(metric: str, company: str) -> list[str]:
        return [w.title for w in warnings if metric in w.metrics and company in w.companies and w.suppresses_peer_points]

    results = risk.evaluate(metrics_all, profile.rules, years, labels, peer_guard, metric_notes)
    return AnalysisResult(
        profile=profile,
        target=resolved[0].name,
        company_names=[c.name for c in resolved],
        first_year=first_year,
        last_year=last_year,
        financials=financials,
        periods=period_frame(financials),
        cleaned=cleaned,
        lineage=lineage,
        metrics_all=metrics_all,
        comparability=warnings,
        rule_results=results,
        scores=risk.scores(results),
    )
