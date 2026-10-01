import pytest

from financial_analyzer.data import companies, sec_client

# Ordered largest-first, like SEC's company_tickers.json.
TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 21344, "ticker": "KO", "title": "COCA COLA CO"},
    "2": {"cik_str": 320187, "ticker": "NKE", "title": "NIKE, Inc."},
    "3": {"cik_str": 1418121, "ticker": "APLE", "title": "Apple Hospitality REIT, Inc."},
    "4": {"cik_str": 200406, "ticker": "JNJ", "title": "JOHNSON & JOHNSON"},
}


@pytest.fixture(autouse=True)
def stub_tickers(monkeypatch):
    monkeypatch.setattr(sec_client, "company_tickers", lambda: TICKERS)


@pytest.mark.parametrize("query, ticker", [
    ("NKE", "NKE"),
    ("nike", "NKE"),
    ("Nike Inc", "NKE"),
    ("Coca-Cola", "KO"),
    ("johnson and johnson", "JNJ"),
    ("apple", "AAPL"),  # exact name beats the larger set of prefix matches
    ("apple hospitality", "APLE"),
])
def test_resolves_tickers_and_company_names(query, ticker):
    assert companies.resolve(query).ticker == ticker


@pytest.mark.parametrize("query", ["adidas", "Adidas", "puma"])
def test_known_non_sec_filer_explains_why(query):
    with pytest.raises(ValueError, match="doesn't file reports with the SEC"):
        companies.resolve(query)


def test_unknown_company_raises():
    with pytest.raises(ValueError, match="Try its ticker symbol"):
        companies.resolve("zzqqxx")


@pytest.mark.parametrize("title, name", [
    ("NIKE, Inc.", "Nike"), ("AT&T INC.", "AT&T"), ("JPMORGAN CHASE & CO", "JPMorgan Chase"),
    ("AMAZON COM INC", "Amazon"), ("TOYOTA MOTOR CORP/", "Toyota Motor"), ("BANK OF AMERICA CORP /DE/", "Bank of America"),
    ("LOWE'S COMPANIES INC", "Lowe's Companies"), ("COCA-COLA EUROPACIFIC PARTNERS plc", "Coca-Cola Europacific Partners"),
    ("SCHWAB CHARLES CORP", "Charles Schwab"), ("KLA CORP", "KLA"),
])
def test_display_names_are_short_and_readable(title, name):
    assert companies.display_name(title) == name
