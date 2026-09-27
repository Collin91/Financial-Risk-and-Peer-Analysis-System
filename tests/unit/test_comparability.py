"""Comparability warnings: OCF classification, captive finance, capex scope."""

from datetime import date

from financial_analyzer.analysis import comparability
from financial_analyzer.data.standardize import standardize

from helpers import company, dec_company, filing, instance


def _toyota_like(receivables_adjustment: float):
    end, start = date(2026, 3, 31), date(2025, 4, 1)
    facts = [("ifrs-full:Revenue", 50_000, start, end), ("ifrs-full:ProfitLossAttributableToOwnersOfParent", 3_800, start, end),
             ("ifrs-full:CashFlowsFromUsedInOperatingActivities", 5_400, start, end),
             ("custom:AdjustmentsForDecreaseIncreaseInReceivablesRelatedToFinancialServices", receivables_adjustment,
              start, end),
             ("ifrs-full:Assets", 100_000, None, end)]
    return standardize(company("Toyota", "TM", 1094517),
                       [instance(filing(1094517, end, "20-F"), 2026, facts, unit="JPY")], 2025, 2025)


def _us_peers():
    return [dec_company("Tesla", "TSLA", 1318605, {2025: {}}, 2025, 2025),
            dec_company("Ford", "F", 37996, {2025: {}}, 2025, 2025)]


def test_material_finance_receivables_in_ocf_raise_suppressing_warning():
    warnings = comparability.assess([*_us_peers(), _toyota_like(-2_000)], range(2025, 2026))
    ocf = next(w for w in warnings if w.key == "ocf_classification")
    assert ocf.companies == ("Toyota",) and ocf.suppresses_peer_points
    assert "ocf_to_net_income" in ocf.metrics
    assert "unadjusted" in ocf.message
    assert comparability.peer_comparison_blocked(warnings, "ocf_to_net_income", ["Tesla", "Toyota"])


def test_immaterial_adjustment_raises_no_ocf_warning():
    warnings = comparability.assess([*_us_peers(), _toyota_like(-100)], range(2025, 2026))  # < 10% of OCF
    assert not any(w.key == "ocf_classification" for w in warnings)


def test_captive_finance_mix_blocks_leverage_and_gross_margin_peer_points():
    warnings = comparability.assess([*_us_peers(), _toyota_like(0)], range(2025, 2026))
    keys = {w.key for w in warnings}
    assert {"captive_finance_leverage", "gross_margin_definition"} <= keys
    assert comparability.peer_comparison_blocked(warnings, "liabilities_to_assets", ["Ford", "Tesla"])
    assert comparability.peer_comparison_blocked(warnings, "gross_margin", ["Tesla", "Ford"])
    gm = next(w for w in warnings if w.key == "gross_margin_definition")
    assert "not automotive gross margins" in gm.message


def test_no_captive_finance_means_no_leverage_or_gross_margin_warning():
    retailers = [dec_company("Walmart", "WMT", 104169, {2025: {}}, 2025, 2025),
                 dec_company("Target", "TGT", 27419, {2025: {}}, 2025, 2025)]
    keys = {w.key for w in comparability.assess(retailers, range(2025, 2026))}
    assert not keys & {"captive_finance_leverage", "gross_margin_definition", "ocf_classification"}


def test_capex_scope_warning_is_informational_and_names_concepts():
    warnings = comparability.assess([*_us_peers(), _toyota_like(0)], range(2025, 2026))
    capex = next(w for w in warnings if w.key == "capex_scope")
    assert not capex.suppresses_peer_points
    assert "PaymentsToAcquirePropertyPlantAndEquipment" in capex.message
