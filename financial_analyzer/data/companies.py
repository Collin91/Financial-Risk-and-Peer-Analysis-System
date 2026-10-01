"""Resolve user input ("Tesla", "TSLA", "Toyota") to an SEC registrant."""

from __future__ import annotations

import re
from dataclasses import dataclass

from financial_analyzer.data import sec_client

# Friendly names -> (ticker, display name). Anything else is looked up in SEC's ticker file.
ALIASES = {
    "tesla": ("TSLA", "Tesla"),
    "ford": ("F", "Ford"),
    "toyota": ("TM", "Toyota"),
    "general motors": ("GM", "General Motors"),
    "gm": ("GM", "General Motors"),
    "honda": ("HMC", "Honda"),
    "stellantis": ("STLA", "Stellantis"),
    "walmart": ("WMT", "Walmart"),
    "target": ("TGT", "Target"),
    "costco": ("COST", "Costco"),
    "home depot": ("HD", "Home Depot"),
    "lowe's": ("LOW", "Lowe's"),
    "lowes": ("LOW", "Lowe's"),
    "kroger": ("KR", "Kroger"),
}
_BY_TICKER = {ticker: display for ticker, display in ALIASES.values()}

# Companies that consolidate a material captive-finance business (customer and dealer
# lending / leasing). Their consolidated balance sheets and cost structures are not
# directly comparable with companies that have no comparable financing operation.
CAPTIVE_FINANCE = {
    "F": "Ford Credit",
    "TM": "Toyota Financial Services",
    "GM": "GM Financial",
    "HMC": "American Honda Finance",
    "STLA": "Stellantis Financial Services",
}


@dataclass(frozen=True)
class Company:
    name: str  # short display name, e.g. "Tesla"
    ticker: str
    cik: int
    registrant: str  # legal name on EDGAR

    @property
    def captive_finance(self) -> str | None:
        return CAPTIVE_FINANCE.get(self.ticker.upper())


def resolve_ticker_hint(name: str) -> str:
    """Ticker for a known friendly name without a network lookup (else the input upper-cased)."""
    return ALIASES.get(name.strip().lower(), (name.strip().upper(),))[0]


# Well-known companies that don't file annual reports with the SEC (foreign companies without
# SEC registration, or private companies), so there is nothing for the analyzer to read.
NON_SEC_FILERS = {
    "adidas": "Adidas", "puma": "Puma", "nestle": "Nestlé", "nestlé": "Nestlé", "lvmh": "LVMH",
    "louis vuitton": "LVMH", "hermes": "Hermès", "hermès": "Hermès", "l'oreal": "L'Oréal",
    "l'oréal": "L'Oréal", "loreal": "L'Oréal", "inditex": "Inditex", "zara": "Inditex (Zara)",
    "h&m": "H&M", "uniqlo": "Fast Retailing (Uniqlo)", "fast retailing": "Fast Retailing",
    "volkswagen": "Volkswagen", "vw": "Volkswagen", "bmw": "BMW", "mercedes": "Mercedes-Benz",
    "mercedes-benz": "Mercedes-Benz", "porsche": "Porsche", "hyundai": "Hyundai",
    "samsung": "Samsung", "bosch": "Bosch", "ikea": "IKEA", "aldi": "Aldi", "lidl": "Lidl",
}

# Legal-form words dropped before comparing names, so "Nike" matches "NIKE, Inc.".
_LEGAL_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
                   "plc", "llc", "lp", "sa", "ag", "nv", "se", "de", "cv", "sab", "the"}


def _name_words(name: str) -> list[str]:
    cleaned = "".join(c if c.isalnum() else " " for c in name.lower().replace("&", " and "))
    return [w for w in cleaned.split() if w not in _LEGAL_SUFFIXES]


def display_name(title: str) -> str:
    """Short, readable name from an EDGAR title: "NIKE, Inc." -> "Nike", "AT&T INC." -> "AT&T"."""
    title = re.sub(r"\s*/[A-Za-z]{1,4}/?$", "", title)  # EDGAR tags such as "/ADR" or "/DE/"
    words = title.replace(",", " ").split()
    while len(words) > 1 and words[-1].lower().replace(".", "") in _LEGAL_SUFFIXES | {"&", "and"}:
        words.pop()
    return " ".join(_word_case(w, first=i == 0) for i, w in enumerate(words)).rstrip(".")


def _word_case(word: str, first: bool) -> str:
    """Fix EDGAR's all-caps or all-lowercase words; keep acronyms (AT&T, 3M, IBM) and mixed case."""
    if word.lower() in {"of", "and", "the", "for"} and not first:
        return word.lower()
    letters = re.sub(r"[-']", "", word)
    if word.islower() or (letters.isupper() and letters.isalpha() and len(letters) > 3):
        return "-".join(p[:1].upper() + p[1:].lower() for p in word.split("-"))
    return word


def _to_company(entry: dict) -> Company:
    name = _BY_TICKER.get(entry["ticker"].upper(), display_name(entry["title"]))
    return Company(name, entry["ticker"], int(entry["cik_str"]), entry["title"])


def resolve(query: str) -> Company:
    q = query.strip()
    ticker = ALIASES[q.lower()][0] if q.lower() in ALIASES else q.upper()
    entries = list(sec_client.company_tickers().values())
    for entry in entries:
        if entry["ticker"].upper() == ticker:
            return _to_company(entry)

    # Checked before the name search, which would otherwise match e.g. "Puma" to Puma Biotechnology.
    if q.lower() in NON_SEC_FILERS:
        raise ValueError(f"{NON_SEC_FILERS[q.lower()]} doesn't file reports with the SEC, so it can't be "
                         "analyzed. Non-US companies often file only in their home country.")

    # Not a ticker: match on the registrant's name. SEC lists the largest companies first,
    # so the first hit is the best-known one ("Apple" -> Apple Inc., not Apple Hospitality REIT).
    words = _name_words(q)
    if words:
        for entry in entries:
            if _name_words(entry["title"]) == words:
                return _to_company(entry)
        for entry in entries:
            if _name_words(entry["title"])[:len(words)] == words:
                return _to_company(entry)
    raise ValueError(f"Could not find an SEC registrant for '{query}'. Try its ticker symbol.")
