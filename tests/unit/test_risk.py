"""Risk rules: first-year prior period, FCF materiality, peer guards, statuses."""

import pandas as pd

from financial_analyzer.analysis import risk
from financial_analyzer.analysis.metrics import all_metrics, displays_equal

from helpers import dec_company, metrics_frame

RULES = {r.id: r for r in risk.GENERAL_RULES}


def _labels(metrics: pd.DataFrame) -> dict:
    return {(c, y): (f"FY{y}", f"{y}-12-31") for c, y in metrics.index}


def _run(metrics, rule_ids, years, **kwargs):
    return risk.evaluate(metrics, [RULES[i] for i in rule_ids], years, _labels(metrics), **kwargs)


def test_first_year_in_window_is_compared_with_base_year():
    cf = dec_company("Tesla", "TSLA", 1, {2020: dict(ca=188, cl=100), 2021: dict(ca=138, cl=100)}, 2020, 2021)
    metrics = all_metrics([cf])
    results = _run(metrics, ["LIQ-2", "PROF-1"], range(2021, 2022))
    by_rule = {r.rule.id: r for r in results}
    assert by_rule["LIQ-2"].status == risk.TRIGGERED  # 1.88x -> 1.38x
    assert "FY2020 1.88x to FY2021 1.38x" in by_rule["LIQ-2"].detail
    assert by_rule["PROF-1"].status == risk.PASSED  # evaluated, not "not evaluated"
    assert all(r.comparison_year == 2021 for r in results)  # base year itself is not scored


def _fcf_metrics(margin_now: float, margin_prev: float) -> pd.DataFrame:
    return metrics_frame({("Ford", 2021): {"fcf_margin": margin_prev}, ("Ford", 2022): {"fcf_margin": margin_now}})


def test_cash3_ignores_slightly_negative_fcf_but_still_reports_it():
    [result] = _run(_fcf_metrics(-0.00008, 0.04), ["CASH-3"], range(2022, 2023))
    assert result.status == risk.PASSED and result.points == 0
    assert "negative" in result.detail and "-0.01%" in result.detail


def test_cash3_triggers_at_minus_half_percent():
    [at] = _run(_fcf_metrics(-0.005, 0.04), ["CASH-3"], range(2022, 2023))
    [below] = _run(_fcf_metrics(-0.012, 0.04), ["CASH-3"], range(2022, 2023))
    [above] = _run(_fcf_metrics(-0.0049, 0.04), ["CASH-3"], range(2022, 2023))
    assert at.triggered and below.triggered and not above.triggered


def test_cash4_uses_same_materiality_threshold():
    [slight] = _run(_fcf_metrics(-0.001, -0.002), ["CASH-4"], range(2022, 2023))
    [material] = _run(_fcf_metrics(-0.01, -0.02), ["CASH-4"], range(2022, 2023))
    assert not slight.triggered and material.triggered


def _peer_metrics(values: dict[str, float], key: str) -> pd.DataFrame:
    return metrics_frame({(name, 2025): {key: v} for name, v in values.items()})


def test_peer_rule_is_informational_with_fewer_than_three_peers():
    m = _peer_metrics({"Ford": 0.88, "Tesla": 0.40, "Toyota": 0.61}, "liabilities_to_assets")
    ford = [r for r in _run(m, ["LEV-1"], range(2025, 2026)) if r.company == "Ford"][0]
    assert ford.status == risk.INFORMATIONAL and ford.points == 0
    assert "at least 3" in ford.detail


def test_peer_rule_assigns_points_with_three_comparable_peers():
    m = _peer_metrics({"A": 0.90, "B": 0.50, "C": 0.55, "D": 0.60}, "liabilities_to_assets")
    a = [r for r in _run(m, ["LEV-1"], range(2025, 2026)) if r.company == "A"][0]
    assert a.status == risk.TRIGGERED and a.points == 2


def test_peer_guard_blocks_non_comparable_leverage_even_with_enough_peers():
    m = _peer_metrics({"A": 0.90, "B": 0.50, "C": 0.55, "D": 0.60}, "liabilities_to_assets")
    guard = lambda metric, names: ["captive finance mix"] if metric == "liabilities_to_assets" else []  # noqa: E731
    a = [r for r in _run(m, ["LEV-1"], range(2025, 2026), peer_guard=guard) if r.company == "A"][0]
    assert a.status == risk.INFORMATIONAL and a.points == 0
    assert "captive finance mix" in a.detail


def test_prof4_requires_three_usable_peers_ignoring_missing_values():
    m = _peer_metrics({"A": 0.01, "B": 0.08, "C": 0.09, "D": float("nan")}, "roa")
    a = [r for r in _run(m, ["PROF-4"], range(2025, 2026)) if r.company == "A"][0]
    assert a.status == risk.INFORMATIONAL  # only 2 usable peers


def test_cash2_not_applicable_in_loss_year():
    m = metrics_frame({("Ford", 2025): {"ocf_to_net_income": float("nan"), "_net_income": -8.0}})
    [r] = _run(m, ["CASH-2"], range(2025, 2026))
    assert r.status == risk.NOT_EVALUATED and "Not applicable" in r.detail


def test_classification_warning_annotates_but_does_not_change_absolute_rule():
    m = metrics_frame({("Toyota", 2024): {"ocf_to_net_income": 0.78, "_net_income": 4.8}})
    notes = lambda metric, co: ["OCF classification differs"] if co == "Toyota" else []  # noqa: E731
    [r] = _run(m, ["CASH-2"], range(2024, 2025), metric_notes=notes)
    assert r.triggered and "comparability warning" in r.detail


def test_results_frame_uses_plain_status_words():
    m = metrics_frame({("Ford", 2025): {"_net_income": -1.0}})
    df = risk.results_frame(_run(m, ["PROF-3", "LIQ-1"], range(2025, 2026)))
    assert set(df["result"]) <= {risk.TRIGGERED, risk.PASSED, risk.INFORMATIONAL, risk.NOT_EVALUATED}
    assert "n/a" not in set(df["result"])
    assert {"rule_name", "reported_fiscal_year", "comparison_year", "period_end"} <= set(df.columns)


def test_every_rule_has_a_plain_english_name_and_known_family():
    from financial_analyzer.analysis.risk import INDUSTRY_RULES
    for rule in [*risk.GENERAL_RULES, *INDUSTRY_RULES.values()]:
        assert rule.name and rule.id.split("-")[0] in risk.RULE_FAMILIES


def test_markers_suppressed_when_values_match_at_display_precision():
    assert displays_equal(0.0656, 0.0661, "pct")  # both "6.6%"
    assert not displays_equal(0.0656, 0.0681, "pct")
