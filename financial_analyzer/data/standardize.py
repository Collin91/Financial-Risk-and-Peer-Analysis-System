"""Map each company's reported XBRL concepts onto one standard set of line items.

Different filers tag the same economic item differently (Tesla: Revenues,
Ford: RevenueFromContractWithCustomerExcludingAssessedTax, Toyota under IFRS:
ifrs-full:Revenue). Each standard line item lists candidate concepts in priority
order; the first one reported for a period wins. When none is reported, a documented
derivation is tried. Every value records where it came from (the lineage) so the
report can show exactly how each number was obtained.

Periods are keyed by comparison year (see xbrl.comparison_year), but each period
keeps the company's own reported fiscal-year label and its exact start/end dates.

Amounts are kept in the reporting currency and also converted to USD.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from financial_analyzer.data import fx, xbrl
from financial_analyzer.data.companies import Company

# Intangible assets (excluding goodwill) below this share of total assets are treated as
# immaterial, so a "productive assets" capex concept is effectively PP&E-only.
INTANGIBLES_MATERIALITY = 0.01

# A finance-receivable adjustment inside operating cash flow of at least this share of
# operating cash flow is treated as a material classification difference.
OCF_RECEIVABLES_MATERIALITY = 0.10


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
    LineItem("operating_cash_flow", "Operating cash flow (reported)", "flow", (
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "ifrs-full:CashFlowsFromUsedInOperatingActivities",
    )),
    # One definition for every company: cash paid for purchases of / additions to property,
    # plant and equipment. Acquisitions, finance receivables, investments, intangible assets and
    # vehicles bought for leasing to customers are excluded. See _validate_capex.
    LineItem("capex", "Capital expenditures (PP&E)", "flow", (
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "custom~^(PurchaseOf|PaymentsToAcquire|PaymentsFor)PropertyPlantAndEquipment(?!.*(Including|Intangible|Business|Acquisition))",
        "us-gaap:PaymentsToAcquireProductiveAssets",  # accepted only if intangibles are immaterial
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

# Supporting items used for derivations and comparability checks only (never in ratios).
SUPPORT_ITEMS = [
    LineItem("operating_expense", "Total operating expenses (IFRS)", "flow", ("ifrs-full:OperatingExpense",)),
    LineItem("sga", "SG&A (IFRS)", "flow", ("ifrs-full:SellingGeneralAndAdministrativeExpense",)),
    LineItem("intangibles", "Intangible assets excl. goodwill", "stock", (
        "us-gaap:IntangibleAssetsNetExcludingGoodwill",
        "us-gaap:FiniteLivedIntangibleAssetsNet",
        "ifrs-full:IntangibleAssetsOtherThanGoodwill",
    )),
    LineItem("fin_receivables_in_ocf", "Finance-receivable change inside operating cash flow", "flow", (
        "custom~^AdjustmentsFor(DecreaseIncrease|IncreaseDecrease)In(?=\\w*Receivable)(?=\\w*Financ)",
        "ifrs-full:AdjustmentsForDecreaseIncreaseInLoansAndAdvancesToCustomers",
    )),
]
SUPPORT_BY_KEY = {item.key: item for item in SUPPORT_ITEMS}
ALL_ITEMS = {**ITEMS_BY_KEY, **SUPPORT_BY_KEY}

# Face-statement lines that some filers tag only with a presentation axis. General Motors,
# for example, has tagged "Automotive and other cost of sales" as
# CostOfGoodsAndServicesSold [BusinessGroupAxis = AutomotiveMember] since its 2022 10-K,
# after tagging the same line without a dimension in earlier years. Such a fact is used
# only when no consolidated candidate exists for the period, and it is cross-checked
# against a period where both versions were reported.
DIMENSIONAL_FALLBACKS = {
    "cost_of_revenue": (("us-gaap:CostOfGoodsAndServicesSold", "BusinessGroupAxis", "AutomotiveMember"),),
}


@dataclass
class Value:
    native: float
    usd: float | None
    source: str  # concept used, or a description of the derivation
    accession: str = ""
    note: str = ""


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    comparison_year: int
    reported_fiscal_year: int
    reported_fy_source: str
    is_base_year: bool = False

    @property
    def label(self) -> str:
        return f"FY{self.reported_fiscal_year}"

    @property
    def ended_text(self) -> str:
        return f"Year ended {long_date(self.end)}"


def long_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def short_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


@dataclass
class CompanyFinancials:
    company: Company
    currency: str
    standard: str  # "US GAAP" or "IFRS"
    periods: dict[int, Period] = field(default_factory=dict)  # comparison year -> period
    fx_rates: dict[int, tuple[float | None, float | None]] = field(default_factory=dict)  # (avg, end)
    values: dict[int, dict[str, Value]] = field(default_factory=dict)  # main line items
    support: dict[int, dict[str, Value]] = field(default_factory=dict)  # supporting items
    forms: tuple[str, ...] = ()  # annual-report forms the figures came from, e.g. ("10-K",)
    warnings: list[str] = field(default_factory=list)


def _is_annual(fact: xbrl.Fact) -> bool:
    return fact.start is not None and 340 <= fact.duration_days <= 380


def _index_facts(facts) -> dict[tuple[str, str], dict[date, xbrl.Fact]]:
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


def _reporting_currency(facts) -> str:
    for concept in ("us-gaap:Assets", "ifrs-full:Assets"):
        units = [f.unit for f in facts if f.qualified == concept]
        if units:
            return max(set(units), key=units.count)
    return "USD"


def _find_period_ends(index, currency: str, first_year: int, last_year: int) -> dict[int, tuple[date, date]]:
    periods: dict[int, tuple[date, date]] = {}
    for concept in ITEMS_BY_KEY["revenue"].candidates + ITEMS_BY_KEY["net_income"].candidates:
        for end, fact in index.get((concept, currency), {}).items():
            cy = xbrl.comparison_year(end)
            if first_year <= cy <= last_year and cy not in periods:
                periods[cy] = (fact.start, end)
    return periods


def _resolve_fiscal_year_labels(ends: dict[int, date], instances: list[xbrl.Instance],
                                warnings: list[str]) -> dict[int, tuple[int, str]]:
    """Reported fiscal year for each period, taken from the filer's own annual report.

    Primary source: dei:DocumentFiscalYearFocus of the annual report whose period ends on that
    date. For a period without its own report in the download (rare), the company's consistent
    offset between reported and comparison year is reused; the source says so.
    """
    labels: dict[int, tuple[int, str]] = {}
    for cy, end in ends.items():
        for inst in instances:
            if abs((inst.period_end - end).days) <= 7 and inst.fiscal_year_focus is not None:
                fy = inst.fiscal_year_focus
                if fy not in (end.year - 1, end.year, end.year + 1):
                    warnings.append(f"Period ended {end}: filing {inst.filing.accession} declares fiscal year "
                                    f"{fy}, which is implausible for that period end; label inferred instead.")
                    break
                labels[cy] = (fy, f"dei:DocumentFiscalYearFocus in {inst.filing.form} {inst.filing.accession}")
                break
    offsets = Counter(fy - cy for cy, (fy, _) in labels.items())
    for cy, end in ends.items():
        if cy in labels:
            continue
        if offsets:
            offset = offsets.most_common(1)[0][0]
            labels[cy] = (cy + offset, "Inferred from the company's labelling of its other fiscal years")
        else:
            labels[cy] = (end.year, "Inferred as the calendar year of the period end (no filing metadata)")
        warnings.append(f"Fiscal-year label for the period ended {end} was inferred: {labels[cy][1]}.")
    return labels


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


def _pick(index, item: LineItem, currency: str, end: date, skip: tuple[str, ...] = ()) -> Value | None:
    for concept in item.candidates:
        if concept in skip:
            continue
        fact = _lookup(index, concept, currency, end, item.kind)
        if fact is not None:
            return Value(fact.value, None, fact.qualified, fact.accession)
    return None


def _dimensional_fallback(key: str, instances: list[xbrl.Instance], index, currency: str, end: date,
                          kind: str) -> Value | None:
    for concept, axis, member in DIMENSIONAL_FALLBACKS.get(key, ()):
        dim_facts = [f for inst in instances for f in inst.dimensional
                     if f.qualified == concept and f.unit == currency and f.dimension == (axis, member)]
        by_end = _index_facts(dim_facts)
        fact = _match_end(by_end.get((concept, currency), {}), end, kind)
        if fact is None:
            continue
        consolidated = index.get((concept, currency), {})
        overlaps = [(e, f.value, consolidated[e].value) for e, f in by_end.get((concept, currency), {}).items()
                    if e in consolidated]
        matched = [e for e, dim_value, plain in overlaps if plain and abs(dim_value / plain - 1) <= 0.005]
        source = f"{concept} [{axis} = {member}]"
        if matched:
            note = (f"Face-statement line tagged only by {axis}; equals the consolidated {concept.split(':')[1]} "
                    f"reported for the period ended {max(matched)}")
        else:
            note = (f"Face-statement line tagged only by {axis}; not cross-checked (no period in the downloaded "
                    f"filings reports both versions)")
        return Value(fact.value, None, source, fact.accession, note)
    return None


def standardize(company: Company, instances: list[xbrl.Instance], first_year: int, last_year: int,
                base_years: tuple[int, ...] = ()) -> CompanyFinancials:
    facts = [f for inst in instances for f in inst.facts]
    currency = _reporting_currency(facts)
    index = _index_facts(facts)
    uses_ifrs = any(q.startswith("ifrs-full:") for q, _ in index)
    result = CompanyFinancials(company, currency, "IFRS" if uses_ifrs else "US GAAP",
                               forms=tuple(sorted({inst.filing.form for inst in instances})))

    spans = _find_period_ends(index, currency, first_year, last_year)
    labels = _resolve_fiscal_year_labels({cy: end for cy, (_, end) in spans.items()}, instances, result.warnings)
    for cy, (start, end) in spans.items():
        fy, source = labels[cy]
        result.periods[cy] = Period(start, end, cy, fy, source, cy in base_years)

    for cy, period in sorted(result.periods.items()):
        row: dict[str, Value] = {}
        for item in LINE_ITEMS:
            value = _pick(index, item, currency, period.end)
            if value is None:
                value = _dimensional_fallback(item.key, instances, index, currency, period.end, item.kind)
                if value is not None and "not cross-checked" in value.note:
                    result.warnings.append(f"{period.label}: {item.label} taken from {value.source} without a "
                                           f"cross-check against a consolidated figure.")
            if value is not None:
                row[item.key] = value
        support = {item.key: v for item in SUPPORT_ITEMS
                   if (v := _pick(index, item, currency, period.end)) is not None}
        _derive(row, support)
        _validate_capex(row, support, index, currency, period, result)
        result.values[cy] = row
        result.support[cy] = support
        _convert(result, cy, period)
        _quality_checks(result, cy)

    missing_years = [cy for cy in range(first_year, last_year + 1) if cy not in result.periods]
    if missing_years:
        result.warnings.append(f"No annual report data found for comparison year(s) {missing_years}.")
    return result


def _accessions(*values: Value | None) -> str:
    return ", ".join(dict.fromkeys(v.accession for v in values if v is not None and v.accession))


def _derive(row: dict[str, Value], support: dict[str, Value]) -> None:
    rev, cost, gp = row.get("revenue"), row.get("cost_of_revenue"), row.get("gross_profit")
    if cost is None and rev and gp:
        row["cost_of_revenue"] = cost = Value(rev.native - gp.native, None, "Derived: revenue - gross profit",
                                              _accessions(rev, gp))
    opex, sga = support.get("operating_expense"), support.get("sga")
    if cost is None and opex and sga:
        # IFRS "function of expense" statements (e.g. Toyota) tag total operating costs and SG&A
        # but tag cost of sales only by segment; cost of sales is the remainder.
        row["cost_of_revenue"] = cost = Value(
            opex.native - sga.native, None,
            "Derived: ifrs-full:OperatingExpense - ifrs-full:SellingGeneralAndAdministrativeExpense",
            _accessions(opex, sga))
    if gp is None and rev and cost:
        row["gross_profit"] = Value(rev.native - cost.native, None, "Derived: revenue - cost of revenue",
                                    _accessions(rev, cost))
    assets, equity = row.get("total_assets"), row.get("total_equity")
    if "total_liabilities" not in row and assets and equity:
        row["total_liabilities"] = Value(assets.native - equity.native, None, "Derived: total assets - total equity",
                                         _accessions(assets, equity))


def _validate_capex(row: dict[str, Value], support: dict[str, Value], index, currency: str, period: Period,
                    result: CompanyFinancials) -> None:
    """Enforce the PP&E-only capex definition.

    us-gaap:PaymentsToAcquireProductiveAssets may include intangible assets, so it is accepted
    only when the company's intangible assets are immaterial; otherwise capex is left missing.
    """
    capex = row.get("capex")
    if capex is None:
        result.warnings.append(f"{period.label}: no PP&E capital-expenditure concept found; capex left missing "
                               "and capex-based rules not evaluated.")
        return
    capex.native = abs(capex.native)  # payments are sometimes tagged negative
    if capex.source != "us-gaap:PaymentsToAcquireProductiveAssets":
        capex.note = "PP&E purchases as reported"
        return
    intangibles, assets = support.get("intangibles"), row.get("total_assets")
    if intangibles is None:
        capex.note = "Productive-assets concept accepted as PP&E: the filer reports no intangible assets"
        return
    share = intangibles.native / assets.native if assets and assets.native else None
    if share is not None and share <= INTANGIBLES_MATERIALITY:
        capex.note = (f"Productive-assets concept accepted as PP&E: intangible assets excl. goodwill are "
                      f"{share:.2%} of total assets")
        return
    del row["capex"]
    result.warnings.append(f"{period.label}: capex reported only as productive assets, and intangible assets are "
                           f"material ({share:.1%} of total assets); capex left missing rather than use a broader "
                           "definition.")


def _convert(result: CompanyFinancials, cy: int, period: Period) -> None:
    if result.currency == "USD":
        avg = spot = 1.0
    else:
        try:
            avg, spot = fx.average_rate(result.currency, period.start, period.end), fx.spot_rate(result.currency,
                                                                                                  period.end)
        except fx.FxUnavailable as exc:
            result.warnings.append(f"{period.label}: {exc}; USD amounts unavailable (ratios are unaffected).")
            avg = spot = None
    result.fx_rates[cy] = (avg, spot)
    for values in (result.values[cy], result.support[cy]):
        for key, value in values.items():
            rate = avg if ALL_ITEMS[key].kind == "flow" else spot
            value.usd = None if rate is None else value.native / rate


def _quality_checks(result: CompanyFinancials, cy: int) -> None:
    row, period = result.values[cy], result.periods[cy]
    missing = [ITEMS_BY_KEY[k].label for k in ITEMS_BY_KEY if k not in row and k not in ("inventory", "capex")]
    if missing:
        result.warnings.append(f"{period.label}: not reported / not found: {', '.join(missing)}.")
    a, l, e = (row.get(k) for k in ("total_assets", "total_liabilities", "total_equity"))
    if a and l and e and a.native:
        gap = abs(a.native - l.native - e.native) / a.native
        if gap > 0.01:  # mezzanine equity (e.g. redeemable NCI) explains small gaps
            result.warnings.append(f"{period.label} (year ended {long_date(period.end)}): assets differ from liabilities + "
                                   f"equity by {gap:.1%} (mezzanine equity or tagging).")


def period_frame(companies: list[CompanyFinancials]) -> pd.DataFrame:
    """Company x comparison-year map of reported fiscal-year labels and period dates."""
    return pd.DataFrame([{
        "company": cf.company.name,
        "reported_fiscal_year": p.label,
        "period_start": p.start.isoformat(),
        "period_end": p.end.isoformat(),
        "comparison_year": cy,
        "is_base_year": p.is_base_year,
        "fiscal_year_label_source": p.reported_fy_source,
    } for cf in companies for cy, p in sorted(cf.periods.items())])


def to_frames(companies: list[CompanyFinancials]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (cleaned financials, lineage) data frames.

    Cleaned financials: one row per company-period, amounts in USD millions.
    Lineage: one row per company-period-line item with the native value, FX rate and source concept.
    """
    wide, lineage = [], []
    for cf in companies:
        for cy, row in sorted(cf.values.items()):
            p = cf.periods[cy]
            avg, spot = cf.fx_rates.get(cy, (None, None))
            ids = {
                "company": cf.company.name,
                "reported_fiscal_year": p.label,
                "period_start": p.start.isoformat(),
                "period_end": p.end.isoformat(),
                "comparison_year": cy,
            }
            record = {
                **ids,
                "ticker": cf.company.ticker,
                "is_base_year": p.is_base_year,
                "accounting_standard": cf.standard,
                "reporting_currency": cf.currency,
                "fx_avg_rate_per_usd": avg,
                "fx_period_end_rate_per_usd": spot,
            }
            for item in LINE_ITEMS:
                v = row.get(item.key)
                record[f"{item.key}_usd_m"] = None if v is None or v.usd is None else v.usd / 1e6
            wide.append(record)
            for item, v, role in ([(i, row.get(i.key), "line item") for i in LINE_ITEMS] +
                                  [(i, cf.support[cy].get(i.key), "supporting") for i in SUPPORT_ITEMS]):
                if v is None:
                    continue
                lineage.append({
                    **ids,
                    "line_item": item.label,
                    "role": role,
                    "native_value_m": v.native / 1e6,
                    "currency": cf.currency,
                    "fx_rate_used": avg if item.kind == "flow" else spot,
                    "fx_basis": "period average" if item.kind == "flow" else "period end",
                    "usd_value_m": None if v.usd is None else v.usd / 1e6,
                    "source": v.source,
                    "note": v.note,
                    "sec_accession": v.accession,
                })
    return pd.DataFrame(wide), pd.DataFrame(lineage)
