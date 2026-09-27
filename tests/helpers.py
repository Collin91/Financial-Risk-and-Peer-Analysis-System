"""Builders for synthetic filings, so tests run without network access."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from financial_analyzer import xbrl
from financial_analyzer.companies import Company
from financial_analyzer.standardize import standardize


def filing(cik: int, fy_end: date, form: str = "10-K", accession: str | None = None) -> xbrl.Filing:
    acc = accession or f"0000000000-{fy_end.year % 100:02d}-{fy_end.month:02d}{cik % 10000:04d}"
    return xbrl.Filing(cik, acc, form, (fy_end + timedelta(days=60)).isoformat(), fy_end.isoformat(), "doc.htm")


def instance(f: xbrl.Filing, fy_focus: int | None, facts: list[tuple], unit: str = "USD") -> xbrl.Instance:
    """facts: (qualified concept, value, start or None, end)."""
    built = []
    for concept, value, start, end in facts:
        taxonomy, local = concept.split(":", 1)
        built.append(xbrl.Fact(taxonomy, local, float(value), unit, start, end, f.accession, f.filed))
    dei = {"DocumentPeriodEndDate": f.report_date}
    if fy_focus is not None:
        dei["DocumentFiscalYearFocus"] = str(fy_focus)
    return xbrl.Instance(f, tuple(built), dei)


def us_gaap_year(end: date, revenue=100.0, cost=80.0, op=10.0, ni=8.0, ocf=12.0, capex=5.0, ca=50.0, cl=40.0,
                 assets=200.0, liabilities=120.0, equity=80.0, inventory=10.0, capex_concept=None) -> list[tuple]:
    start = date(end.year - 1, end.month, end.day) + timedelta(days=1)
    flows = [("us-gaap:Revenues", revenue), ("us-gaap:CostOfRevenue", cost), ("us-gaap:OperatingIncomeLoss", op),
             ("us-gaap:NetIncomeLoss", ni), ("us-gaap:NetCashProvidedByUsedInOperatingActivities", ocf),
             (capex_concept or "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", capex)]
    stocks = [("us-gaap:AssetsCurrent", ca), ("us-gaap:LiabilitiesCurrent", cl), ("us-gaap:Assets", assets),
              ("us-gaap:Liabilities", liabilities), ("us-gaap:StockholdersEquity", equity),
              ("us-gaap:InventoryNet", inventory)]
    return [(c, v, start, end) for c, v in flows if v is not None] + [(c, v, None, end) for c, v in stocks]


def company(name: str, ticker: str = "TST", cik: int = 1) -> Company:
    return Company(name, ticker, cik, name.upper())


def dec_company(name: str, ticker: str, cik: int, years: dict[int, dict], first: int, last: int):
    """A calendar-year US GAAP filer; years maps calendar year -> overrides for us_gaap_year."""
    instances = []
    for y, overrides in years.items():
        f = filing(cik, date(y, 12, 31))
        instances.append(instance(f, y, us_gaap_year(date(y, 12, 31), **overrides)))
    return standardize(company(name, ticker, cik), instances, first, last, base_years=(first,))


def metrics_frame(rows: dict[tuple[str, int], dict]) -> pd.DataFrame:
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index = pd.MultiIndex.from_tuples(df.index, names=["company", "comparison_year"])
    return df
