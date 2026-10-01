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
    # Technology
    "apple": ("AAPL", "Apple"),
    "microsoft": ("MSFT", "Microsoft"),
    "alphabet": ("GOOGL", "Alphabet"),
    "google": ("GOOGL", "Alphabet"),
    "meta": ("META", "Meta Platforms"),
    "nvidia": ("NVDA", "Nvidia"),
    "oracle": ("ORCL", "Oracle"),
    # Pharmaceuticals
    "pfizer": ("PFE", "Pfizer"),
    "merck": ("MRK", "Merck"),
    "johnson & johnson": ("JNJ", "Johnson & Johnson"),
    "eli lilly": ("LLY", "Eli Lilly"),
    "abbvie": ("ABBV", "AbbVie"),
    "bristol-myers squibb": ("BMY", "Bristol-Myers Squibb"),
    # Apparel & footwear
    "nike": ("NKE", "Nike"),
    "under armour": ("UAA", "Under Armour"),
    "lululemon": ("LULU", "Lululemon"),
    "deckers": ("DECK", "Deckers"),
    "vf corp": ("VFC", "VF Corp"),
    "columbia sportswear": ("COLM", "Columbia Sportswear"),
    "on holding": ("ONON", "On Holding"),
    # Consumer goods
    "procter & gamble": ("PG", "Procter & Gamble"),
    "colgate-palmolive": ("CL", "Colgate-Palmolive"),
    "kimberly-clark": ("KMB", "Kimberly-Clark"),
    "coca-cola": ("KO", "Coca-Cola"),
    "pepsico": ("PEP", "PepsiCo"),
    "kraft heinz": ("KHC", "Kraft Heinz"),
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
                   "plc", "llc", "lp", "sa", "ag", "nv", "se", "de", "cv", "sab", "the", "com"}

# Brand spellings an all-caps EDGAR title can't tell us ("JPMORGAN" -> "JPMorgan", "LAM" -> "Lam").
_WORD_CASE = {w.upper(): w for w in (
    "JPMorgan", "HSBC", "ASML", "UnitedHealth", "PepsiCo", "AstraZeneca", "Eli", "Lam", "Rio", "Nvidia",
    "BlackRock", "McDonald's", "McKesson", "FedEx", "eBay", "PayPal", "HP", "NXP", "ConocoPhillips",
    "ExxonMobil", "GlaxoSmithKline", "AbbVie", "CVS", "UPS", "AutoZone", "O'Reilly", "Ford", "Kraft", "Heinz")}
_WORD_CASE["MCDONALDS"] = "McDonald's"
# Whole names EDGAR stores in an unusual order.
_TITLE_NAMES = {"SCHWAB CHARLES CORP": "Charles Schwab"}


def _name_words(name: str) -> list[str]:
    cleaned = "".join(c if c.isalnum() else " " for c in name.lower().replace("&", " and "))
    return [w for w in cleaned.split() if w not in _LEGAL_SUFFIXES]


def possessive(name: str) -> str:
    """ "Nike" -> "Nike's", "Deckers" -> "Deckers'"."""
    return name + ("'" if name.endswith("s") else "'s")


def display_name(title: str) -> str:
    """Short, readable name from an EDGAR title: "NIKE, Inc." -> "Nike", "AT&T INC." -> "AT&T"."""
    if title.upper() in _TITLE_NAMES:
        return _TITLE_NAMES[title.upper()]
    title = re.sub(r"\s*/([A-Za-z]{1,4}/?)?$", "", title)  # EDGAR tags such as "/ADR", "/DE/" or a bare "/"
    words = title.replace(",", " ").split()
    while len(words) > 1 and words[-1].lower().replace(".", "") in _LEGAL_SUFFIXES | {"&", "and"}:
        words.pop()
    return " ".join(_word_case(w, first=i == 0) for i, w in enumerate(words)).rstrip(".")


def _word_case(word: str, first: bool) -> str:
    """Fix EDGAR's all-caps or all-lowercase words; keep acronyms (AT&T, 3M, IBM) and mixed case."""
    if word.isupper() and word in _WORD_CASE:
        return _WORD_CASE[word]
    if word.lower() in {"of", "and", "the", "for"} and not first:
        return word.lower()
    letters = re.sub(r"[-']", "", word)
    if word.islower() or (letters.isupper() and letters.isalpha() and len(letters) > 3):
        return "-".join(p[:1].upper() + p[1:].lower() for p in word.split("-"))
    return word


def to_company(entry: dict) -> Company:
    name = _BY_TICKER.get(entry["ticker"].upper(), display_name(entry["title"]))
    return Company(name, entry["ticker"], int(entry["cik_str"]), entry["title"])


def resolve(query: str) -> Company:
    q = query.strip()
    ticker = ALIASES[q.lower()][0] if q.lower() in ALIASES else q.upper()
    entries = list(sec_client.company_tickers().values())
    for entry in entries:
        if entry["ticker"].upper() == ticker:
            return to_company(entry)

    # Checked before the name search, which would otherwise match e.g. "Puma" to Puma Biotechnology.
    if q.lower() in NON_SEC_FILERS:
        raise ValueError(f"{NON_SEC_FILERS[q.lower()]} doesn't file reports with the SEC, so it can't be "
                         "analyzed. Non-US companies often file only in their home country.")

    # Not a ticker: match on the registrant's name. SEC lists the largest companies first,
    # so the first hit is the best-known one ("Apple" -> Apple Inc., not Apple Hospitality REIT).
    words = _name_words(q)
    # Names EDGAR stores in an unusual order ("Charles Schwab" is "SCHWAB CHARLES CORP").
    words = next((_name_words(title) for title, name in _TITLE_NAMES.items() if _name_words(name) == words), words)
    if words:
        for entry in entries:
            if _name_words(entry["title"]) == words:
                return to_company(entry)
        for entry in entries:
            if _name_words(entry["title"])[:len(words)] == words:
                return to_company(entry)
    raise ValueError(f"Could not find an SEC registrant for '{query}'. Try its ticker symbol.")
