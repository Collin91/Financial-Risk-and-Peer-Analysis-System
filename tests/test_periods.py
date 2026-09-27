"""Fiscal-year labels, period dates and comparison years."""

from datetime import date

from financial_analyzer import xbrl
from financial_analyzer.standardize import standardize

from helpers import company, filing, instance


def _ifrs_year(end: date, revenue: float) -> list[tuple]:
    start = date(end.year - 1, 4, 1)
    return [("ifrs-full:Revenue", revenue, start, end),
            ("ifrs-full:ProfitLossAttributableToOwnersOfParent", revenue * 0.08, start, end),
            ("ifrs-full:Assets", revenue * 2, None, end)]


def test_comparison_year_uses_calendar_year_containing_most_of_the_period():
    assert xbrl.comparison_year(date(2026, 3, 31)) == 2025  # Toyota FY2026
    assert xbrl.comparison_year(date(2025, 12, 31)) == 2025  # Tesla / Ford FY2025
    assert xbrl.comparison_year(date(2026, 1, 31)) == 2025  # Walmart FY2026
    assert xbrl.comparison_year(date(2025, 8, 31)) == 2025  # Costco FY2025
    assert xbrl.comparison_year(date(2025, 6, 30)) == 2025


def test_toyota_keeps_its_official_fiscal_year_label():
    instances = []
    for fy in (2025, 2026):
        end = date(fy, 3, 31)
        instances.append(instance(filing(1094517, end, "20-F"), fy, _ifrs_year(end, 100.0 * fy), unit="JPY"))
    cf = standardize(company("Toyota", "TM", 1094517), instances, 2024, 2025)

    period = cf.periods[2025]
    assert period.label == "FY2026"  # never renamed to FY2025
    assert period.end == date(2026, 3, 31)
    assert period.start == date(2025, 4, 1)
    assert period.comparison_year == 2025
    assert period.ended_text == "Year ended March 31, 2026"
    assert "DocumentFiscalYearFocus" in period.reported_fy_source
    assert cf.periods[2024].label == "FY2025"


def test_retailer_label_comes_from_filing_not_period_end_year():
    # Target labels its year ended February 1, 2025 as fiscal 2024; that must be preserved.
    end = date(2025, 2, 1)
    f = filing(27419, end)
    start = date(2024, 2, 4)
    facts = [("us-gaap:Revenues", 100, start, end), ("us-gaap:NetIncomeLoss", 5, start, end),
             ("us-gaap:Assets", 50, None, end)]
    cf = standardize(company("Target", "TGT", 27419), [instance(f, 2024, facts)], 2024, 2024)
    assert cf.periods[2024].label == "FY2024"


def test_missing_label_is_inferred_from_companys_other_years_and_flagged():
    labelled_end, unlabelled_end = date(2026, 3, 31), date(2025, 3, 31)
    facts = _ifrs_year(labelled_end, 200) + _ifrs_year(unlabelled_end, 190)
    cf = standardize(company("Toyota", "TM", 1094517),
                     [instance(filing(1094517, labelled_end, "20-F"), 2026, facts, unit="JPY")], 2024, 2025)
    assert cf.periods[2024].label == "FY2025"
    assert "Inferred" in cf.periods[2024].reported_fy_source
    assert any("inferred" in w for w in cf.warnings)
