"""Foreign-exchange conversion to USD using Federal Reserve H.10 rates via FRED.

Flow items (income statement, cash flow) are converted at the average daily rate
over the fiscal period; balance-sheet items at the rate on the period-end date
(or the last business day before it).
"""

from __future__ import annotations

import csv
import io
from datetime import date
from functools import lru_cache

from . import sec_client

# currency -> (FRED series, True if the series is quoted as foreign units per USD)
FRED_SERIES = {
    "JPY": ("DEXJPUS", True),
    "EUR": ("DEXUSEU", False),
    "GBP": ("DEXUSUK", False),
    "CAD": ("DEXCAUS", True),
    "CHF": ("DEXSZUS", True),
    "CNY": ("DEXCHUS", True),
    "KRW": ("DEXKOUS", True),
    "INR": ("DEXINUS", True),
    "MXN": ("DEXMXUS", True),
    "TWD": ("DEXTAUS", True),
    "SEK": ("DEXSDUS", True),
    "BRL": ("DEXBZUS", True),
}


class FxUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=None)
def _series(currency: str) -> list[tuple[date, float]]:
    """Daily rates expressed as foreign units per 1 USD, oldest first."""
    if currency not in FRED_SERIES:
        raise FxUnavailable(f"No FX series configured for {currency}")
    series_id, foreign_per_usd = FRED_SERIES[currency]
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        body = sec_client.fetch(url, f"fx/{series_id}.csv", max_age_hours=24).decode()
    except Exception as exc:  # network failure, FRED outage
        raise FxUnavailable(f"Could not download {series_id} from FRED: {exc}") from exc
    rows = []
    for row in csv.reader(io.StringIO(body)):
        if len(row) != 2 or not row[1] or row[1] == "." or not row[0][:1].isdigit():
            continue
        rate = float(row[1])
        rows.append((date.fromisoformat(row[0]), rate if foreign_per_usd else 1 / rate))
    return rows


def average_rate(currency: str, start: date, end: date) -> float:
    rates = [r for d, r in _series(currency) if start <= d <= end]
    if not rates:
        raise FxUnavailable(f"No {currency} rates between {start} and {end}")
    return sum(rates) / len(rates)


def spot_rate(currency: str, on: date) -> float:
    prior = [r for d, r in _series(currency) if d <= on]
    if not prior:
        raise FxUnavailable(f"No {currency} rate on or before {on}")
    return prior[-1]
