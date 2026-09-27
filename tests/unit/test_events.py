"""SEC Event Context module: ranking helpers (offline)."""

from financial_analyzer import events
from financial_analyzer.events import SignificantChange

PROFIT_CHANGE = SignificantChange("Ford", 2025, "FY2025", events.PROFITABILITY, "Operating margin",
                                  "Operating margin -7.7 pp (FY2024 to FY2025)")
DEBT_CHANGE = SignificantChange("Ford", 2025, "FY2025", events.DEBT, "Liabilities-to-assets",
                                "Liabilities-to-assets +3.3 pp (FY2024 to FY2025)")


def test_keyword_relevance_depends_on_affected_area():
    sentence = "We recorded an $8.4 billion pre-tax non-cash impairment charge for our Model e long-lived assets."
    assert events._score_sentence(sentence, events.PROFITABILITY)[0] >= 1.0
    assert events._score_sentence(sentence, events.DEBT)[0] < 1.0


def test_boilerplate_and_tables_are_not_treated_as_events():
    text = ("Forward-looking statements involve risks and uncertainties, including recalls and litigation that "
            "could cause results to differ. Selling, general and administrative $ 5,834 $ 5,150 $ 4,800 $ 684 13 % "
            "$ 350 7 % As a percentage of revenues 6 % 5 % 5 %. The aggregate expected pre-tax charge from the "
            "impairment of our battery joint venture is estimated to be about $3 billion.")
    kept = events._sentences(text)
    assert len(kept) == 1 and "pre-tax charge" in kept[0]


def test_item_code_amount_and_proximity_raise_ranking():
    text = ("We concluded that we will recognize an impairment of our remaining investment in the joint venture. "
            "The aggregate expected pre-tax charge is estimated to be about $3 billion for the quarter.")
    with_item = events._best_in_text(text, [PROFIT_CHANGE, DEBT_CHANGE], ["2.06"], 1.0, annual_note=False)
    without = events._best_in_text(text, [PROFIT_CHANGE, DEBT_CHANGE], [], 0.4, annual_note=False)
    assert with_item[2] is PROFIT_CHANGE
    assert with_item[0] > without[0]


def test_tariff_keyword_ignores_utility_rate_tariffs():
    assert not events._KEYWORD_RES["tariffs"].search("discounts to the base tariff energy rates")
    assert events._KEYWORD_RES["tariffs"].search("the impact of U.S. tariffs on operating income")


def test_relevance_labels():
    assert [events._relevance_label(s) for s in (4.7, 3.0, 2.0)] == ["High", "Medium", "Low"]
