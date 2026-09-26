"""Locate annual reports on EDGAR and extract facts from their XBRL instances.

The instance document of each 10-K / 20-F is parsed directly instead of relying
on SEC's companyfacts summary API, because that API omits company-specific
(extension) concepts and can lag behind newly filed IFRS reports.

Only facts without dimensions (i.e. consolidated, whole-company figures) are kept.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from . import sec_client

ANNUAL_FORMS = {"10-K", "20-F", "40-F"}

_XBRLI = "{http://www.xbrl.org/2003/instance}"


@dataclass(frozen=True)
class Filing:
    cik: int
    accession: str
    form: str
    filed: str
    report_date: str
    primary_document: str

    @property
    def fiscal_year(self) -> int:
        return fiscal_year_label(date.fromisoformat(self.report_date))


@dataclass(frozen=True)
class Fact:
    taxonomy: str  # "us-gaap", "ifrs-full", "dei" or "custom"
    concept: str  # local name, e.g. "Revenues"
    value: float
    unit: str  # ISO currency code or "pure"/"shares"
    start: date | None  # None for balance-sheet (instant) facts
    end: date
    accession: str
    filed: str

    @property
    def qualified(self) -> str:
        return f"{self.taxonomy}:{self.concept}"

    @property
    def duration_days(self) -> int | None:
        return None if self.start is None else (self.end - self.start).days + 1


def fiscal_year_label(period_end: date) -> int:
    """Label a fiscal year by the calendar year that contains most of it.

    Years ending January-May are assigned to the prior calendar year (the
    Compustat convention), so Toyota's year ended 31 March 2026 is FY2025 and
    lines up with Tesla's and Ford's calendar 2025.
    """
    return period_end.year if period_end.month >= 6 else period_end.year - 1


def annual_filings(cik: int, first_fy: int, last_fy: int) -> list[Filing]:
    subs = sec_client.submissions(cik)
    blocks = [subs["filings"]["recent"]]
    for extra in subs["filings"].get("files", []):
        # Older filings are paged out; only fetch pages that could overlap the range.
        if extra.get("filingTo", "9999") >= f"{first_fy}-01-01":
            blocks.append(sec_client.fetch_json(
                f"https://data.sec.gov/submissions/{extra['name']}",
                f"submissions/{extra['name']}",
                max_age_hours=24 * 30,
            ))

    by_year: dict[int, Filing] = {}
    for block in blocks:
        for i, form in enumerate(block["form"]):
            if form not in ANNUAL_FORMS or not block["reportDate"][i]:
                continue
            f = Filing(
                cik=cik,
                accession=block["accessionNumber"][i],
                form=form,
                filed=block["filingDate"][i],
                report_date=block["reportDate"][i],
                primary_document=block["primaryDocument"][i],
            )
            if first_fy <= f.fiscal_year <= last_fy:
                current = by_year.get(f.fiscal_year)
                if current is None or f.filed > current.filed:
                    by_year[f.fiscal_year] = f
    return [by_year[y] for y in sorted(by_year)]


def _instance_name(filing: Filing) -> str:
    items = [it["name"] for it in sec_client.filing_index(filing.cik, filing.accession)["directory"]["item"]]
    for name in items:
        if name.endswith("_htm.xml"):  # instance extracted from inline XBRL
            return name
    skip = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml", "FilingSummary.xml")
    candidates = [n for n in items if n.endswith(".xml") and not n.endswith(skip)]
    if not candidates:
        raise sec_client.SecError(f"No XBRL instance found in filing {filing.accession}")
    return candidates[0]


def _taxonomy(namespace: str) -> str:
    if "fasb.org/us-gaap" in namespace:
        return "us-gaap"
    if "xbrl.ifrs.org" in namespace:
        return "ifrs-full"
    if "xbrl.sec.gov/dei" in namespace:
        return "dei"
    if "fasb.org/srt" in namespace:
        return "srt"
    return "custom"


def filing_facts(filing: Filing) -> list[Fact]:
    raw = sec_client.filing_file(filing.cik, filing.accession, _instance_name(filing))
    root = ET.fromstring(raw)

    contexts: dict[str, tuple[date | None, date]] = {}
    for ctx in root.iter(_XBRLI + "context"):
        if ctx.find(f"{_XBRLI}entity/{_XBRLI}segment") is not None or ctx.find(_XBRLI + "scenario") is not None:
            continue  # dimensional context: a segment, product line, etc.
        period = ctx.find(_XBRLI + "period")
        instant = period.findtext(_XBRLI + "instant")
        if instant:
            contexts[ctx.get("id")] = (None, date.fromisoformat(instant.strip()[:10]))
        else:
            contexts[ctx.get("id")] = (
                date.fromisoformat(period.findtext(_XBRLI + "startDate").strip()[:10]),
                date.fromisoformat(period.findtext(_XBRLI + "endDate").strip()[:10]),
            )

    units: dict[str, str] = {}
    for unit in root.iter(_XBRLI + "unit"):
        measures = unit.findall(_XBRLI + "measure")
        if len(measures) == 1:  # skip ratios such as USD/share
            units[unit.get("id")] = measures[0].text.split(":")[-1].strip()

    facts = []
    for el in root:
        ctx_ref, unit_ref = el.get("contextRef"), el.get("unitRef")
        if ctx_ref not in contexts or unit_ref not in units or el.text is None:
            continue
        try:
            value = float(el.text.strip())
        except ValueError:
            continue
        namespace, local = el.tag[1:].split("}")
        start, end = contexts[ctx_ref]
        facts.append(Fact(_taxonomy(namespace), local, value, units[unit_ref], start, end,
                          filing.accession, filing.filed))
    return facts
