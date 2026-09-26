"""Map each company's reported XBRL concepts onto one standard set of line items.

Different filers tag the same economic item differently (Tesla: Revenues,
Ford: RevenueFromContractWithCustomerExcludingAssessedTax, Toyota under IFRS:
ifrs-full:Revenue). Each standard line item lists candidate concepts in priority
order; the first one reported for a year wins. When none is reported, a documented
derivation is tried. Every value records where it came from (the lineage) so the
report can show exactly how each number was obtained.

Amounts are kept in the reporting currency and also converted to USD.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from . import fx, xbrl
from .companies import Company


@dataclass(frozen=True)
class LineItem:
    key: str
    label: str
    kind: str  # "flow" (period total) or "stock" (balance at period end)
    candidates: tuple[str, ...]  # "taxonomy:Concept", or "custom~regex" for company extension concepts


LINE_ITEMS = [
    LineItem("revenue", "Revenue", "flow", (
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
        "us-gaap:SalesRevenueNet",
        "ifrs-full:Revenue",
    )),
    LineItem("cost_of_revenue", "Cost of revenue", "flow", (
        "us-gaap:CostOfRevenue",
        "us-gaap:CostOfGoodsAndServicesSold",
        "us-gaap:CostOfGoodsSold",
        "us-gaap:CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
        "ifrs-full:CostOfSales",
    )),
    LineItem("gross_profit", "Gross profit", "flow", (
        "us-gaap:GrossProfit",
        "ifrs-full:GrossProfit",
    )),
    LineItem("operating_income", "Operating income", "flow", (
        "us-gaap:OperatingIncomeLoss",
        "ifrs-full:ProfitLossFromOperatingActivities",
    )),
    LineItem("net_income", "Net income (to parent)", "flow", (
        "us-gaap:NetIncomeLoss",
        "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic",
        "ifrs-full:ProfitLossAttributableToOwnersOfParent",
        "us-gaap:ProfitLoss",
        "ifrs-full:ProfitLoss",
    )),
    LineItem("operating_cash_flow", "Operating cash flow", "flow", (
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "ifrs-full:CashFlowsFromUsedInOperatingActivities",
    )),
    LineItem("capex", "Capital expenditures", "flow", (
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "us-gaap:PaymentsToAcquireProductiveAssets",
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "custom~^(PurchaseOf|PaymentsToAcquire)PropertyPlantAndEquipment",
    )),
    LineItem("inventory", "Inventory", "stock", (
        "us-gaap:InventoryNet",
        "us-gaap:InventoryFinishedGoods",
        "ifrs-full:Inventories",
    )),
    LineItem("current_assets", "Current assets", "stock", (
        "us-gaap:AssetsCurrent",
        "ifrs-full:CurrentAssets",
    )),
    LineItem("current_liabilities", "Current liabilities", "stock", (
        "us-gaap:LiabilitiesCurrent",
        "ifrs-full:CurrentLiabilities",
    )),
    LineItem("total_assets", "Total assets", "stock", (
        "us-gaap:Assets",
        "ifrs-full:Assets",
    )),
    LineItem("total_liabilities", "Total liabilities", "stock", (
        "us-gaap:Liabilities",
        "ifrs-full:Liabilities",
    )),
    LineItem("total_equity", "Total equity", "stock", (
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "us-gaap:StockholdersEquity",
        "ifrs-full:Equity",
    )),
]
ITEMS_BY_KEY = {item.key: item for item in LINE_ITEMS}

# Concepts pulled only to support derivations.
_AUX = {
    "operating_expense": "ifrs-full:OperatingExpense",
    "sga": "ifrs-full:SellingGeneralAndAdministrativeExpense",
    "liabilities_and_equity": "us-gaap:LiabilitiesAndStockholdersEquity",
}


@dataclass
class Value:
    native: float
    usd: float | None
    source: str  # concept used, or a description of the derivation
    accession: str = ""


@dataclass
class CompanyFinancials:
    company: Company
    currency: str
    standard: str  # "US GAAP" or "IFRS"
    periods: dict[int, tuple[date, date]] = field(default_factory=dict)  # fy -> (start, end)
    fx_rates: dict[int, tuple[float | None, float | None]] = field(default_factory=dict)  # fy -> (avg, end)
    values: dict[int, dict[str, Value]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _is_annual(fact: xbrl.Fact) -> bool:
    return fact.start is not None and 340 <= fact.duration_days <= 380


def _index_facts(facts: list[xbrl.Fact]) -> dict[tuple[str, str], dict[date, xbrl.Fact]]:
    """(qualified concept, unit) -> period end -> latest-filed fact.

    The newest filing wins, so restated comparatives replace originally reported numbers.
    """
    index: dict[tuple[str, str], dict[date, xbrl.Fact]] = {}
    for f in facts:
        if f.start is not None and not _is_annual(f):
            continue  # quarterly or odd-length period
        by_end = index.setdefault((f.qualified, f.unit), {})
        current = by_end.get(f.end)
        if current is None or f.filed > current.filed:
            by_end[f.end] = f
    return index


def _reporting_currency(facts: list[xbrl.Fact]) -> str:
    for concept in ("us-gaap:Assets", "ifrs-full:Assets"):
        units = [f.unit for f in facts if f.qualified == concept]
        if units:
            return max(set(units), key=units.count)
    return "USD"


def _find_period_ends(index, currency: str, first_fy: int, last_fy: int) -> dict[int, tuple[date, date]]:
    periods: dict[int, tuple[date, date]] = {}
    for concept in ITEMS_BY_KEY["revenue"].candidates + ITEMS_BY_KEY["net_income"].candidates:
        for end, fact in index.get((concept, currency), {}).items():
            fy = xbrl.fiscal_year_label(end)
            if first_fy <= fy <= last_fy and fy not in periods:
                periods[fy] = (fact.start, end)
    return periods


def _lookup(index, concept: str, currency: str, end: date, kind: str) -> xbrl.Fact | None:
    if concept.startswith("custom~"):
        pattern = re.compile(concept.split("~", 1)[1])
        matches = [(q, by_end) for (q, unit), by_end in index.items()
                   if unit == currency and q.startswith("custom:") and pattern.search(q.split(":", 1)[1])]
        # Shortest name = least qualified, most general concept.
        for _, by_end in sorted(matches, key=lambda m: len(m[0])):
            fact = _match_end(by_end, end, kind)
            if fact:
                return fact
        return None
    return _match_end(index.get((concept, currency), {}), end, kind)


def _match_end(by_end: dict[date, xbrl.Fact], end: date, kind: str) -> xbrl.Fact | None:
    # Allow a few days' slack: 52/53-week filers' balance sheet dates can differ from the flow period end.
    for delta in (0, 1, -1, 2, -2, 3, -3):
        fact = by_end.get(end + timedelta(days=delta))
        if fact is not None and (fact.start is None) == (kind == "stock"):
            return fact
    return None


def standardize(company: Company, facts: list[xbrl.Fact], first_fy: int, last_fy: int) -> CompanyFinancials:
    currency = _reporting_currency(facts)
    index = _index_facts(facts)
    uses_ifrs = any(q.startswith("ifrs-full:") for q, _ in index)
    result = CompanyFinancials(company, currency, "IFRS" if uses_ifrs else "US GAAP")
    result.periods = _find_period_ends(index, currency, first_fy, last_fy)

    for fy, (start, end) in sorted(result.periods.items()):
        row: dict[str, Value] = {}
        for item in LINE_ITEMS:
            for concept in item.candidates:
                fact = _lookup(index, concept, currency, end, item.kind)
                if fact is not None:
                    row[item.key] = Value(fact.value, None, fact.qualified, fact.accession)
                    break
        aux = {k: _lookup(index, c, currency, end, "stock" if k == "liabilities_and_equity" else "flow")
               for k, c in _AUX.items()}
        _derive(row, aux)
        if "capex" in row:
            row["capex"].native = abs(row["capex"].native)  # payments are sometimes tagged negative
        result.values[fy] = row
        _convert(result, fy, start, end)
        _quality_checks(result, fy, aux)

    missing_years = [fy for fy in range(first_fy, last_fy + 1) if fy not in result.periods]
    if missing_years:
        result.warnings.append(f"No annual report data found for fiscal year(s) {missing_years}.")
    return result


def _derive(row: dict[str, Value], aux: dict[str, xbrl.Fact | None]) -> None:
    rev, cost, gp = row.get("revenue"), row.get("cost_of_revenue"), row.get("gross_profit")
    if cost is None and rev and gp:
        row["cost_of_revenue"] = cost = Value(rev.native - gp.native, None, "Derived: revenue - gross profit")
    if cost is None and aux["operating_expense"] and aux["sga"]:
        # IFRS "function of expense" statements (e.g. Toyota) tag total operating costs and SG&A
        # but tag cost of sales only by segment; cost of sales is the remainder.
        row["cost_of_revenue"] = cost = Value(
            aux["operating_expense"].value - aux["sga"].value, None,
            "Derived: ifrs-full:OperatingExpense - ifrs-full:SellingGeneralAndAdministrativeExpense",
            aux["operating_expense"].accession)
    if gp is None and rev and cost:
        row["gross_profit"] = Value(rev.native - cost.native, None, "Derived: revenue - cost of revenue")
    if "total_liabilities" not in row and "total_assets" in row and "total_equity" in row:
        row["total_liabilities"] = Value(row["total_assets"].native - row["total_equity"].native, None,
                                         "Derived: total assets - total equity")


def _convert(result: CompanyFinancials, fy: int, start: date, end: date) -> None:
    row = result.values[fy]
    if result.currency == "USD":
        avg = spot = 1.0
    else:
        try:
            avg, spot = fx.average_rate(result.currency, start, end), fx.spot_rate(result.currency, end)
        except fx.FxUnavailable as exc:
            result.warnings.append(f"FY{fy}: {exc}; USD amounts unavailable (ratios are unaffected).")
            avg = spot = None
    result.fx_rates[fy] = (avg, spot)
    for key, value in row.items():
        rate = avg if ITEMS_BY_KEY[key].kind == "flow" else spot
        value.usd = None if rate is None else value.native / rate


def _quality_checks(result: CompanyFinancials, fy: int, aux: dict[str, xbrl.Fact | None]) -> None:
    row = result.values[fy]
    missing = [ITEMS_BY_KEY[k].label for k in ITEMS_BY_KEY if k not in row and k != "inventory"]
    if missing:
        result.warnings.append(f"FY{fy}: not reported / not found: {', '.join(missing)}.")
    a, l, e = (row.get(k) for k in ("total_assets", "total_liabilities", "total_equity"))
    if a and l and e and a.native:
        gap = abs(a.native - l.native - e.native) / a.native
        if gap > 0.01:  # mezzanine equity (e.g. redeemable NCI) explains small gaps
            result.warnings.append(
                f"FY{fy}: assets differ from liabilities + equity by {gap:.1%} (mezzanine equity or tagging).")


def to_frames(companies: list[CompanyFinancials]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (cleaned financials, lineage) data frames.

    Cleaned financials: one row per company-year, amounts in USD millions.
    Lineage: one row per company-year-line item with the native value, FX rate and source concept.
    """
    wide, lineage = [], []
    for cf in companies:
        for fy, row in sorted(cf.values.items()):
            start, end = cf.periods[fy]
            avg, spot = cf.fx_rates.get(fy, (None, None))
            record = {
                "company": cf.company.name,
                "ticker": cf.company.ticker,
                "fiscal_year": fy,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "accounting_standard": cf.standard,
                "reporting_currency": cf.currency,
                "fx_avg_rate_per_usd": avg,
                "fx_period_end_rate_per_usd": spot,
            }
            for item in LINE_ITEMS:
                v = row.get(item.key)
                record[f"{item.key}_usd_m"] = None if v is None or v.usd is None else v.usd / 1e6
            wide.append(record)
            for item in LINE_ITEMS:
                v = row.get(item.key)
                if v is None:
                    continue
                lineage.append({
                    "company": cf.company.name,
                    "fiscal_year": fy,
                    "line_item": item.label,
                    "native_value_m": v.native / 1e6,
                    "currency": cf.currency,
                    "fx_rate_used": avg if item.kind == "flow" else spot,
                    "fx_basis": "period average" if item.kind == "flow" else "period end",
                    "usd_value_m": None if v.usd is None else v.usd / 1e6,
                    "source": v.source,
                    "sec_accession": v.accession,
                })
    return pd.DataFrame(wide), pd.DataFrame(lineage)
