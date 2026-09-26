"""Resolve user input ("Tesla", "TSLA", "Toyota") to an SEC registrant."""

from __future__ import annotations

from dataclasses import dataclass

from . import sec_client

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


@dataclass(frozen=True)
class Company:
    name: str  # short display name, e.g. "Tesla"
    ticker: str
    cik: int
    registrant: str  # legal name on EDGAR


def resolve(query: str) -> Company:
    q = query.strip()
    ticker = ALIASES[q.lower()][0] if q.lower() in ALIASES else q.upper()
    for entry in sec_client.company_tickers().values():
        if entry["ticker"].upper() == ticker:
            name = _BY_TICKER.get(ticker, entry["title"].title())
            return Company(name, entry["ticker"], int(entry["cik_str"]), entry["title"])
    raise ValueError(f"Could not find an SEC registrant for '{query}'. Try its ticker symbol.")
