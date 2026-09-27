"""Concept mapping, derivations, capex scope and lineage."""

from datetime import date

from financial_analyzer.data.standardize import standardize, to_frames

from helpers import company, filing, instance, us_gaap_year


def _single_year(facts, ticker="TST"):
    end = date(2025, 12, 31)
    return standardize(company("Co", ticker, 5), [instance(filing(5, end), 2025, facts)], 2025, 2025)


def test_ifrs_cost_of_revenue_derived_from_operating_expense_minus_sga_with_accession():
    end, start = date(2026, 3, 31), date(2025, 4, 1)
    f = filing(1094517, end, "20-F")
    facts = [("ifrs-full:Revenue", 50_685, start, end), ("ifrs-full:OperatingExpense", 46_918.7, start, end),
             ("ifrs-full:SellingGeneralAndAdministrativeExpense", 4_697.5, start, end),
             ("ifrs-full:ProfitLossAttributableToOwnersOfParent", 3_848, start, end),
             ("ifrs-full:Assets", 105_522, None, end)]
    cf = standardize(company("Toyota", "TM", 1094517), [instance(f, 2026, facts, unit="JPY")], 2025, 2025)
    cost = cf.values[2025]["cost_of_revenue"]
    assert round(cost.native, 1) == 42_221.2
    assert cost.source.startswith("Derived: ifrs-full:OperatingExpense")
    assert cost.accession == f.accession  # derived values keep their source filing
    assert cf.values[2025]["gross_profit"].accession == f.accession


def test_capex_prefers_ppe_concept():
    cf = _single_year(us_gaap_year(date(2025, 12, 31), capex=7))
    assert cf.values[2025]["capex"].source == "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"


def test_productive_assets_accepted_only_when_intangibles_immaterial():
    end = date(2025, 12, 31)
    base = us_gaap_year(end, capex=9, assets=1000, capex_concept="us-gaap:PaymentsToAcquireProductiveAssets")

    small = base + [("us-gaap:FiniteLivedIntangibleAssetsNet", 5, None, end)]  # 0.5% of assets
    cf = _single_year(small)
    assert cf.values[2025]["capex"].native == 9
    assert "accepted as PP&E" in cf.values[2025]["capex"].note

    large = base + [("us-gaap:FiniteLivedIntangibleAssetsNet", 80, None, end)]  # 8% of assets
    cf = _single_year(large)
    assert "capex" not in cf.values[2025]  # left missing rather than use a broader definition
    assert any("capex left missing" in w for w in cf.warnings)


def test_custom_ppe_concept_excludes_leased_equipment_variants():
    end, start = date(2026, 3, 31), date(2025, 4, 1)
    facts = [("ifrs-full:Revenue", 100, start, end), ("ifrs-full:ProfitLoss", 5, start, end),
             ("ifrs-full:Assets", 300, None, end),
             ("custom:PurchaseOfPropertyPlantAndEquipmentIncludingEquipmentLeasedToOthers", 50, start, end),
             ("custom:PurchaseOfPropertyPlantAndEquipmentExcludingEquipmentLeasedToOthers", 20, start, end)]
    cf = standardize(company("Toyota", "TM", 1094517),
                     [instance(filing(1094517, end, "20-F"), 2026, facts, unit="JPY")], 2025, 2025)
    capex = cf.values[2025]["capex"]
    assert capex.native == 20
    assert "Excluding" in capex.source


def test_frames_carry_reported_label_period_dates_comparison_year_and_base_flag():
    instances = []
    for y in (2024, 2025):
        end = date(y, 12, 31)
        instances.append(instance(filing(7, end), y, us_gaap_year(end)))
    cf = standardize(company("Co", "CO", 7), instances, 2024, 2025, base_years=(2024,))
    cleaned, lineage = to_frames([cf])
    assert list(cleaned[["reported_fiscal_year", "comparison_year", "is_base_year"]].itertuples(index=False,
                                                                                               name=None)) == [
        ("FY2024", 2024, True), ("FY2025", 2025, False)]
    assert {"period_start", "period_end", "sec_accession", "note"} <= set(lineage.columns)
    assert lineage["sec_accession"].ne("").all()
