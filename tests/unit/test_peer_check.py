"""Peer fit check based on SEC industry codes (no network: submissions are stubbed)."""

import pytest

from financial_analyzer.analysis import peer_check
from financial_analyzer.data import sec_client

from helpers import company

SUBMISSIONS = {
    1: {"sic": "3711", "sicDescription": "Motor Vehicles & Passenger Car Bodies", "fiscalYearEnd": "1231"},  # Tesla
    2: {"sic": "3711", "sicDescription": "Motor Vehicles & Passenger Car Bodies", "fiscalYearEnd": "1231"},  # Ford
    3: {"sic": "3711", "sicDescription": "Motor Vehicles & Passenger Car Bodies", "fiscalYearEnd": "0331"},  # Toyota
    4: {"sic": "5331", "sicDescription": "Retail-Variety Stores", "fiscalYearEnd": "0131"},  # Walmart
    5: {"sic": "3714", "sicDescription": "Motor Vehicle Parts & Accessories", "fiscalYearEnd": "1231"},  # parts maker
    6: {"sic": "5211", "sicDescription": "Retail-Lumber & Other Building Materials Dealers", "fiscalYearEnd": "0131"},
}


@pytest.fixture(autouse=True)
def stub_sec(monkeypatch):
    monkeypatch.setattr(sec_client, "submissions", lambda cik: SUBMISSIONS[cik])


TESLA, FORD, TOYOTA, WALMART, PARTS, HOME = (company(n, t, c) for n, t, c in [
    ("Tesla", "TSLA", 1), ("Ford", "F", 2), ("Toyota", "TM", 3), ("Walmart", "WMT", 4), ("PartsCo", "PC", 5),
    ("Home Depot", "HD", 6)])


def test_classification_levels():
    assert peer_check.classify("3711", "3711") == peer_check.SAME
    assert peer_check.classify("3711", "3714") == peer_check.RELATED
    assert peer_check.classify("5331", "5211") == peer_check.SECTOR  # both retail trade
    assert peer_check.classify("3711", "5331") == peer_check.DIFFERENT
    assert peer_check.classify("3711", "") == peer_check.UNKNOWN


def test_footwear_and_apparel_are_related_but_other_manufacturers_are_not():
    assert peer_check.classify("3021", "2300") == peer_check.RELATED  # Nike vs Under Armour
    assert peer_check.classify("2300", "3021") == peer_check.RELATED
    assert peer_check.classify("3021", "2834") == peer_check.SECTOR  # footwear vs pharmaceuticals


def test_good_peer_group_has_no_warnings_about_fit():
    check = peer_check.check(TESLA, [FORD, TOYOTA])
    assert all(f.ok for f in check.peers) and not check.mismatches


def test_different_sector_peer_is_flagged_with_explanation():
    check = peer_check.check(TESLA, [FORD, WALMART])
    assert [f.profile.company.name for f in check.mismatches] == ["Walmart"]
    assert any("Retail-Variety Stores" in n and "not" in n for n in check.notes)


def test_retailers_in_different_industries_are_same_sector_mismatch():
    check = peer_check.check(WALMART, [HOME])
    assert check.peers[0].match == peer_check.SECTOR and check.mismatches


def test_fewer_than_three_peers_explains_scoring_and_suggests_more():
    check = peer_check.check(TESLA, [FORD, TOYOTA], suggestions=[FORD, TOYOTA, PARTS])
    note = next(n for n in check.notes if "peer median" in n)
    assert "Add 1 more" in note and "PartsCo" in note


def test_different_year_ends_are_explained():
    check = peer_check.check(TESLA, [TOYOTA])
    assert any("Toyota's on Mar 31" in n for n in check.notes)


def test_sec_outage_never_blocks(monkeypatch):
    def boom(cik):
        raise RuntimeError("offline")
    monkeypatch.setattr(sec_client, "submissions", boom)
    check = peer_check.check(TESLA, [FORD])
    assert check.peers[0].match == peer_check.UNKNOWN


def test_suggestions_exclude_companies_from_other_industries():
    check = peer_check.check(TESLA, [FORD], suggestions=[WALMART, TOYOTA, HOME])
    note = next(n for n in check.notes if "peer median" in n)
    assert "Toyota" in note and "Walmart" not in note and "Home Depot" not in note


def test_no_matching_suggestion_asks_for_same_industry_company():
    check = peer_check.check(WALMART, [company("Costco", "COST", 4)], suggestions=[HOME])
    note = next(n for n in check.notes if "peer median" in n)
    assert "from Walmart's industry" in note


def test_similar_companies_are_largest_first_and_exclude_the_target(monkeypatch):
    # Ticker file order = size order; Toyota (cik 3) is listed under two tickers.
    tickers = {"0": {"cik_str": 4, "ticker": "WMT", "title": "Walmart Inc."},
               "1": {"cik_str": 3, "ticker": "TM", "title": "TOYOTA MOTOR CORP/"},
               "2": {"cik_str": 1, "ticker": "TSLA", "title": "Tesla, Inc."},
               "3": {"cik_str": 3, "ticker": "TOYOF", "title": "TOYOTA MOTOR CORP/"},
               "4": {"cik_str": 2, "ticker": "F", "title": "FORD MOTOR CO"}}
    monkeypatch.setattr(sec_client, "company_tickers", lambda: tickers)
    monkeypatch.setattr(sec_client, "companies_in_sic", lambda sic, progress=None: [2, 1, 3] if sic == "3711" else [])
    assert [c.ticker for c in peer_check.similar_companies(TESLA)] == ["TM", "F"]


def test_similar_companies_never_raise(monkeypatch):
    def boom(*args, **kwargs):
        raise sec_client.SecError("offline")
    monkeypatch.setattr(sec_client, "companies_in_sic", boom)
    assert peer_check.similar_companies(TESLA) == []


def test_possessive_names():
    from financial_analyzer.data.companies import possessive
    assert possessive("Nike") == "Nike's" and possessive("Deckers") == "Deckers'"
