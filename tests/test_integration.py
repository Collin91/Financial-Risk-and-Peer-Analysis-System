"""End-to-end check against real SEC filings (uses the local download cache).

Skipped when the filings are not cached and the network is unavailable.
"""

from datetime import date

import pytest

from financial_analyzer import analysis, industries, risk


@pytest.fixture(scope="module")
def result():
    try:
        return analysis.run("Tesla", ["Ford", "Toyota"], industries.get_profile("automotive"), 2021, 2025,
                            progress=lambda *a: None)
    except Exception as exc:  # no cache and no network
        pytest.skip(f"SEC data unavailable: {exc}")


def test_toyota_periods_keep_official_labels(result):
    p = result.period("Toyota", 2025)
    assert (p.label, p.end, p.comparison_year) == ("FY2026", date(2026, 3, 31), 2025)
    assert result.period("Toyota", 2021).label == "FY2022"
    assert result.period("Tesla", 2025).label == "FY2025"
    assert result.period("Ford", 2025).end == date(2025, 12, 31)


def test_toyota_values_tie_to_20f(result):
    toyota = next(cf for cf in result.financials if cf.company.name == "Toyota")
    row = toyota.values[2025]
    assert round(row["revenue"].native / 1e9, 1) == 50_685.0
    assert round(row["operating_income"].native / 1e9, 1) == 3_766.2
    assert round(row["cost_of_revenue"].native / 1e9, 1) == 42_221.2
    assert round(row["capex"].native / 1e9, 1) == 2_148.2
    assert toyota.currency == "JPY" and toyota.standard == "IFRS"


def test_first_year_rules_are_evaluated(result):
    first = [r for r in result.rule_results if r.comparison_year == 2021 and r.rule.id in ("PROF-1", "LIQ-2", "LEV-2")]
    assert first and all(r.status in (risk.TRIGGERED, risk.PASSED) for r in first)
    tesla_liq2 = next(r for r in first if r.company == "Tesla" and r.rule.id == "LIQ-2")
    assert tesla_liq2.triggered


def test_peer_rules_assign_no_points_for_three_company_set(result):
    peer = [r for r in result.rule_results if r.rule.id in ("PROF-4", "LEV-1")]
    assert peer and all(r.points == 0 for r in peer)


def test_expected_comparability_warnings(result):
    keys = {w.key for w in result.comparability}
    assert {"ocf_classification", "captive_finance_leverage", "gross_margin_definition", "capex_scope"} <= keys


def test_ford_2022_slightly_negative_fcf_not_flagged(result):
    r = next(r for r in result.rule_results if r.company == "Ford" and r.comparison_year == 2022
             and r.rule.id == "CASH-3")
    assert not r.triggered and "negative" in r.detail
