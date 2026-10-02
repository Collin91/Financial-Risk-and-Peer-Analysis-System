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


def test_oracle_cost_of_revenue_is_sum_of_direct_cost_lines():
    end, start = date(2026, 5, 31), date(2025, 6, 1)
    facts = [("us-gaap:Revenues", 67_355, start, end), ("us-gaap:NetIncomeLoss", 17_000, start, end),
             ("custom:CloudAndSoftwareExpenses", 17_601, start, end), ("custom:HardwareExpenses", 870, start, end),
             ("custom:ServicesExpense", 4_560, start, end)]
    cf = standardize(company("Oracle", "ORCL", 1341439), [instance(filing(1341439, end), 2026, facts)], 2025, 2025)
    assert cf.values[2025]["cost_of_revenue"].native == 23_031
    assert cf.values[2025]["gross_profit"].native == 44_324

    partial = [f for f in facts if f[0] != "custom:HardwareExpenses"]  # never sum an incomplete set
    cf = standardize(company("Oracle", "ORCL", 1341439), [instance(filing(1341439, end), 2026, partial)], 2025, 2025)
    assert "cost_of_revenue" not in cf.values[2025]


def test_capex_prefers_ppe_concept():
    cf = _single_year(us_gaap_year(date(2025, 12, 31), capex=7))
    assert cf.values[2025]["capex"].source == "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"


def test_productive_assets_used_and_flagged_when_intangibles_are_material():
    end = date(2025, 12, 31)
    base = us_gaap_year(end, capex=9, assets=1000, capex_concept="us-gaap:PaymentsToAcquireProductiveAssets")

    small = base + [("us-gaap:FiniteLivedIntangibleAssetsNet", 5, None, end)]  # 0.5% of assets
    cf = _single_year(small)
    assert cf.values[2025]["capex"].native == 9
    assert "accepted as PP&E" in cf.values[2025]["capex"].note

    large = base + [("us-gaap:FiniteLivedIntangibleAssetsNet", 80, None, end)]  # 8% of assets
    cf = _single_year(large)
    assert cf.values[2025]["capex"].native == 9  # used, not left missing
    assert "may also include purchases of intangible assets" in cf.values[2025]["capex"].note
    assert any("productive-assets" in w for w in cf.warnings)


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


def _gm_like(with_overlap: bool):
    """Cost of sales tagged plainly for 2021, then only by business group from 2022 (as GM does)."""
    axis = ("BusinessGroupAxis", "AutomotiveMember")
    old_end, new_end = date(2021, 12, 31), date(2022, 12, 31)
    old = us_gaap_year(old_end, cost=None, revenue=127_004)
    old = [f for f in old if f[0] != "us-gaap:CostOfRevenue"] + [
        ("us-gaap:CostOfGoodsAndServicesSold", 100_544, date(2021, 1, 1), old_end)]
    new = [f for f in us_gaap_year(new_end, cost=None, revenue=156_735) if f[0] != "us-gaap:CostOfRevenue"]
    dims = [("us-gaap:CostOfGoodsAndServicesSold", 126_892, date(2022, 1, 1), new_end, axis)]
    if with_overlap:
        dims.append(("us-gaap:CostOfGoodsAndServicesSold", 100_544, date(2021, 1, 1), old_end, axis))
    instances = [instance(filing(1467858, old_end), 2021, old),
                 instance(filing(1467858, new_end), 2022, new, dimensional=dims)]
    return standardize(company("General Motors", "GM", 1467858), instances, 2021, 2022)


def test_face_line_tagged_by_business_group_is_used_and_cross_checked():
    cf = _gm_like(with_overlap=True)
    cost = cf.values[2022]["cost_of_revenue"]
    assert cost.native == 126_892
    assert "BusinessGroupAxis" in cost.source and "equals the consolidated" in cost.note
    assert cf.values[2021]["cost_of_revenue"].source == "us-gaap:CostOfGoodsAndServicesSold"  # plain fact preferred
    assert round(cf.values[2022]["gross_profit"].native) == 156_735 - 126_892


def test_dimensional_fallback_without_overlap_is_flagged():
    cf = _gm_like(with_overlap=False)
    assert "not cross-checked" in cf.values[2022]["cost_of_revenue"].note
    assert any("without a cross-check" in w for w in cf.warnings)


def test_other_dimensions_are_never_used():
    end = date(2025, 12, 31)
    facts = [f for f in us_gaap_year(end, cost=None) if f[0] != "us-gaap:CostOfRevenue"]
    segment = [("us-gaap:CostOfGoodsAndServicesSold", 50, date(2025, 1, 1), end, ("StatementGeographicalAxis", "US"))]
    cf = standardize(company("Co", "CO", 9), [instance(filing(9, end), 2025, facts, dimensional=segment)], 2025, 2025)
    assert "cost_of_revenue" not in cf.values[2025]


def test_forms_are_recorded():
    cf = _gm_like(with_overlap=True)
    assert cf.forms == ("10-K",)


def _no_operating_income_line(pretax):
    """Nike-style statement: gross profit, SG&A, non-operating items, pre-tax income; no operating-income line."""
    end = date(2025, 12, 31)
    start = date(2025, 1, 1)
    return us_gaap_year(end, op=None) + [
        ("us-gaap:GrossProfit", 20, start, end), ("us-gaap:SellingGeneralAndAdministrativeExpense", 12, start, end),
        ("us-gaap:InterestIncomeExpenseNonoperatingNet", -1, start, end),
        ("us-gaap:OtherNonoperatingIncomeExpense", 0.5, start, end),
        ("us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
         pretax, start, end)]


def test_operating_income_derived_from_gross_profit_minus_sga_when_it_reconciles():
    oi = _single_year(_no_operating_income_line(pretax=7.5)).values[2025]["operating_income"]
    assert oi.native == 8
    assert oi.source == "Derived: gross profit - us-gaap:SellingGeneralAndAdministrativeExpense"


def test_operating_income_left_missing_when_sga_is_not_the_only_operating_expense():
    # Pre-tax income 3 lower than gross profit - SG&A + non-operating items: another operating line exists.
    assert "operating_income" not in _single_year(_no_operating_income_line(pretax=4.5)).values[2025]


def test_lifo_inventory_derived_from_fifo_cost_minus_reserve():
    end = date(2025, 12, 31)
    facts = [f for f in us_gaap_year(end) if f[0] != "us-gaap:InventoryNet"]
    facts += [("us-gaap:FIFOInventoryAmount", 9.4, None, end),
                                                 ("us-gaap:InventoryLIFOReserve", 2.5, None, end)]
    inventory = _single_year(facts).values[2025]["inventory"]
    assert round(inventory.native, 1) == 6.9
    assert inventory.source.startswith("Derived: us-gaap:FIFOInventoryAmount")


def test_duplicated_fiscal_year_label_in_filer_metadata_is_corrected():
    # Kroger-style: the reports for years ending early 2024 and 2025 declare 2024 and 2025 instead of 2023 and 2024.
    declared = {2023: 2022, 2024: 2024, 2025: 2025, 2026: 2025}
    instances = [instance(filing(7, date(y, 1, 31)), fy, us_gaap_year(date(y, 1, 31))) for y, fy in declared.items()]
    cf = standardize(company("Grocer", "GRC", 7), instances, 2022, 2025)
    assert [p.label for _, p in sorted(cf.periods.items())] == ["FY2022", "FY2023", "FY2024", "FY2025"]
    assert sum("corrected" in w for w in cf.warnings) == 2
