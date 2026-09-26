"""End-to-end pipeline: download -> standardize -> metrics -> comparison -> risk flags."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import companies as companies_mod
from . import risk, xbrl
from .industries import IndustryProfile
from .metrics import all_metrics
from .standardize import CompanyFinancials, standardize, to_frames


@dataclass
class AnalysisResult:
    profile: IndustryProfile
    target: str
    company_names: list[str]
    first_fy: int
    last_fy: int
    financials: list[CompanyFinancials]
    cleaned: pd.DataFrame  # USD millions, one row per company-year (includes the prior base year)
    lineage: pd.DataFrame
    metrics: pd.DataFrame  # indexed by (company, fiscal_year)
    rule_results: list[risk.RuleResult]
    scores: pd.DataFrame

    @property
    def latest_year(self) -> int:
        return int(self.metrics.index.get_level_values("fiscal_year").max())

    @property
    def warnings(self) -> list[str]:
        return [f"{cf.company.name}: {w}" for cf in self.financials for w in cf.warnings]

    def peer_comparison(self, year: int) -> pd.DataFrame:
        """Metrics (rows) x companies (columns) for one year, plus each metric's peer median."""
        table = self.metrics.xs(year, level="fiscal_year")[self.profile.metric_keys].T
        table = table[[c for c in self.company_names if c in table.columns]]
        table["Peer median (excl. target)"] = table.drop(columns=[self.target], errors="ignore").median(axis=1)
        return table

    def target_vs_history(self) -> pd.DataFrame:
        """Target's latest year against its own average over the earlier years in the window."""
        m = self.metrics.xs(self.target, level="company")[self.profile.metric_keys]
        latest = self.latest_year
        history = m[m.index < latest]
        return pd.DataFrame({
            "latest": m.loc[latest] if latest in m.index else pd.Series(dtype=float),
            "prior_average": history.mean(),
            "prior_min": history.min(),
            "prior_max": history.max(),
        })


def run(target: str, peers: list[str], profile: IndustryProfile, first_fy: int, last_fy: int,
        progress=print) -> AnalysisResult:
    resolved = [companies_mod.resolve(q) for q in [target, *peers]]
    financials = []
    for company in resolved:
        progress(f"Downloading annual reports for {company.name} ({company.ticker}, CIK {company.cik})...")
        # One extra year back so the first year in the window has growth rates and averages.
        filings = xbrl.annual_filings(company.cik, first_fy - 1, last_fy)
        if not filings:
            raise RuntimeError(f"No 10-K/20-F filings found for {company.name} in FY{first_fy - 1}-{last_fy}")
        facts = [fact for filing in filings for fact in xbrl.filing_facts(filing)]
        progress(f"  {len(filings)} filings ({', '.join(f'{f.form} FY{f.fiscal_year}' for f in filings)})")
        financials.append(standardize(company, facts, first_fy - 1, last_fy))

    cleaned, lineage = to_frames(financials)
    metrics = all_metrics(financials, first_fy, last_fy)
    results = risk.evaluate(metrics, profile.rules)
    return AnalysisResult(
        profile=profile,
        target=resolved[0].name,
        company_names=[c.name for c in resolved],
        first_fy=first_fy,
        last_fy=last_fy,
        financials=financials,
        cleaned=cleaned,
        lineage=lineage,
        metrics=metrics,
        rule_results=results,
        scores=risk.scores(results),
    )
