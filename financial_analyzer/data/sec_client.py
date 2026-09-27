"""Thin, cached client for the SEC EDGAR endpoints used by the analyzer.

SEC's fair-access policy requires a descriptive User-Agent with contact details
and at most 10 requests per second. Set the SEC_USER_AGENT environment variable
to something like "Your Name your.email@example.com".
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

DEFAULT_USER_AGENT = "FinancialAnalyzer research tool contact@example.com"
CACHE_DIR = Path(os.environ.get("FA_CACHE_DIR", Path(__file__).resolve().parents[2] / ".cache"))

_MIN_INTERVAL = 0.15  # seconds between live requests (< 10 req/s)
_last_request = 0.0


class SecError(RuntimeError):
    pass


def _user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT)


def _get(url: str) -> bytes:
    global _last_request
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": _user_agent(), "Accept-Encoding": "gzip, deflate"}
    for attempt in range(3):
        _last_request = time.monotonic()
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        raise SecError(f"GET {url} failed with HTTP {resp.status_code}")
    raise SecError(f"GET {url} kept failing (rate limited); set SEC_USER_AGENT and retry later")


def fetch(url: str, cache_name: str, max_age_hours: float | None = None) -> bytes:
    """Return the body for url, reading from / writing to the on-disk cache.

    Filing documents never change, so they are cached forever (max_age_hours=None).
    Index-style endpoints (submissions, ticker list) pass a max age.
    """
    path = CACHE_DIR / cache_name
    if path.exists():
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        if max_age_hours is None or age_hours < max_age_hours:
            return path.read_bytes()
    body = _get(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def fetch_json(url: str, cache_name: str, max_age_hours: float | None = None) -> dict:
    return json.loads(fetch(url, cache_name, max_age_hours))


def company_tickers() -> dict:
    return fetch_json("https://www.sec.gov/files/company_tickers.json", "company_tickers.json", max_age_hours=24 * 7)


def submissions(cik: int) -> dict:
    return fetch_json(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
        f"submissions/CIK{cik:010d}.json",
        max_age_hours=24,
    )


def filing_index(cik: int, accession: str) -> dict:
    acc = accession.replace("-", "")
    return fetch_json(
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json",
        f"filings/{cik}/{acc}/index.json",
    )


def filing_file(cik: int, accession: str, name: str) -> bytes:
    acc = accession.replace("-", "")
    return fetch(
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{name}",
        f"filings/{cik}/{acc}/{name}",
    )
