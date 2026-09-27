"""SEC Event Context: potential explanatory events for significant financial changes.

This module is optional and kept separate from the financial calculations and risk
scoring. It never changes reported figures or scores. Events are context only; a
match does not establish that the event caused the change.

For each company period with a significant change (profitability, cash flow, debt,
revenue, inventory or capital expenditures), it searches:
  * 8-K filings (U.S. companies) and 6-K filings (foreign private issuers) made during
    the fiscal period or within 75 days after it ends, including press-release exhibits
  * the annual report (10-K / 20-F) for that period
for keywords such as restructuring, impairment, recall, acquisition, divestiture,
litigation, regulatory settlement, strike, plant closure, severance, production
disruption and unusual charges, then ranks candidates by keyword relevance, filing-date
proximity, whether an amount is stated, and whether the text comes from an annual-report
note.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from financial_analyzer.data import sec_client

DISCLAIMER = ("These events are drawn automatically from SEC filings made during or shortly after each fiscal "
              "period. They provide context only and do not establish causation. Reported figures and risk scores "
              "are never adjusted because of an event match.")

AFTER_PERIOD_DAYS = 75  # year-end charges are often announced with annual results
MAX_FILINGS_PER_PERIOD = 30  # current-report texts fetched per company period
MAX_EXHIBITS_PER_FILING = 2
MAX_DOCUMENT_BYTES = 4_000_000
EVENTS_PER_PERIOD = 3

PROFITABILITY, CASH_FLOW, DEBT, REVENUE, INVENTORY, CAPEX = (
    "profitability", "cash flow", "debt", "revenue", "inventory", "capital expenditures")


@dataclass(frozen=True)
class SignificantChange:
    company: str
    comparison_year: int
    reported_fiscal_year: str
    area: str  # profitability, cash flow, debt, revenue, inventory, capital expenditures
    metric: str  # metric label
    description: str


@dataclass(frozen=True)
class Event:
    company: str
    comparison_year: int
    reported_fiscal_year: str
    event_date: str
    filing_type: str
    description: str
    relevance: str  # High / Medium / Low
    score: float
    affected_metric: str
    change: str  # the significant change this event may relate to
    url: str


# keyword group -> (pattern, areas it can explain)
KEYWORDS = {
    "restructuring": (r"restructur", {PROFITABILITY, CASH_FLOW}),
    "impairment": (r"impairment|write-?downs?\b|write-?offs?\b", {PROFITABILITY}),
    "recall": (r"\brecalls?\b", {PROFITABILITY, CASH_FLOW, REVENUE}),
    "warranty": (r"warranty (?:cost|expense|accrual|reserve)", {PROFITABILITY, CASH_FLOW}),
    "acquisition": (r"\bacquisition of\b|\bto acquire\b|\bacquired\b", {REVENUE, DEBT, CAPEX, CASH_FLOW}),
    "divestiture": (r"divest|\bsale of (?:its|our|the) [\w\s-]{0,40}(?:business|subsidiary|stake|operations|unit)",
                    {REVENUE, DEBT, PROFITABILITY}),
    "litigation": (r"litigation|lawsuit|class action", {PROFITABILITY, CASH_FLOW}),
    "regulatory settlement": (r"settlement|consent order|civil penalt|\bpenalt(?:y|ies)\b", {PROFITABILITY, CASH_FLOW}),
    "strike": (r"\bstrikes?\b|work stoppage|labor dispute", {REVENUE, INVENTORY, PROFITABILITY}),
    "plant closure": (r"plant closure|clos(?:e|ing|ure of) (?:the |its |a |our )?(?:plant|factory|facility)",
                      {PROFITABILITY, CAPEX}),
    "severance": (r"severance|layoffs?\b|workforce reduction|headcount reduction", {PROFITABILITY, CASH_FLOW}),
    "production disruption": (r"production (?:disruption|halt|suspension|stoppage|shutdown)|suspend(?:ed)? production|"
                              r"supply(?: chain)? disruption|parts? shortage", {REVENUE, INVENTORY, PROFITABILITY}),
    "unusual charges": (r"(?:special|one-time|non-recurring|unusual) (?:items?|charges?)|\bcharges? of\b|"
                        r"pre-tax charges?|non-cash charges?",
                        {PROFITABILITY}),
    "tariffs": (r"\btariffs\b|tariff (?:impact|costs?|expenses?|headwinds?)", {PROFITABILITY}),
    "financing": (r"senior notes|notes offering|credit (?:agreement|facility)|term loan|debt (?:issuance|offering)",
                  {DEBT}),
    "capital investment": (r"capital expenditures?|capital spending|new (?:plant|factory)|capacity expansion|"
                           r"gigafactory", {CAPEX}),
}
_KEYWORD_RES = {name: re.compile(pattern, re.I) for name, (pattern, _) in KEYWORDS.items()}

# 8-K item codes that signal the kind of event (and the areas they relate to).
ITEM_SIGNALS = {
    "2.05": ("exit or disposal costs", {PROFITABILITY, CASH_FLOW}),
    "2.06": ("material impairment", {PROFITABILITY}),
    "2.01": ("acquisition or disposition of assets", {REVENUE, DEBT, CAPEX}),
    "1.01": ("material definitive agreement", {DEBT, CAPEX}),
    "1.02": ("termination of material agreement", {REVENUE, PROFITABILITY}),
    "2.03": ("new direct financial obligation", {DEBT}),
    "2.04": ("triggering event accelerating an obligation", {DEBT}),
}
_SEARCHED_ITEMS = set(ITEM_SIGNALS) | {"2.02", "7.01", "8.01"}

_AMOUNT = re.compile(r"(?:US\$|\$|¥|JPY\s?|USD\s?)\s?\d[\d,.]*(?:\s?(?:billion|million|trillion|bn|mn))?|"
                     r"\d[\d,.]*\s?(?:billion|million|trillion)\s(?:yen|dollars)", re.I)


# --- significant-change detection (independent of the risk rules) ------------------------------

def detect_changes(result, years: list[int]) -> list[SignificantChange]:
    m = result.metrics_all
    changes = []
    for company in result.company_names:
        for year in years:
            if (company, year) not in m.index or (company, year - 1) not in m.index:
                continue
            cur, prev = m.loc[(company, year)], m.loc[(company, year - 1)]
            p, pp = result.period(company, year), result.period(company, year - 1)
            span = f"{pp.label} to {p.label}"

            def add(area: str, metric: str, text: str) -> None:
                changes.append(SignificantChange(company, year, p.label, area, metric, text))

            if _big(cur["operating_margin"] - prev["operating_margin"], 0.02):
                add(PROFITABILITY, "Operating margin", f"Operating margin {_pp(cur['operating_margin'] - prev['operating_margin'])} ({span})")
            ni, ni_prev = cur["_net_income"], prev["_net_income"]
            if _ok(ni, ni_prev) and (ni * ni_prev < 0 or (ni_prev and abs(ni / ni_prev - 1) >= 0.5)):
                add(PROFITABILITY, "Net income", f"Net income {_pct_change(ni, ni_prev)} ({span})")
            ocf, ocf_prev = cur["_ocf"], prev["_ocf"]
            if _ok(ocf, ocf_prev) and ocf_prev and abs(ocf / ocf_prev - 1) >= 0.25:
                add(CASH_FLOW, "Operating cash flow", f"Reported operating cash flow {_pct_change(ocf, ocf_prev)} ({span})")
            if _big(cur["liabilities_to_assets"] - prev["liabilities_to_assets"], 0.03):
                add(DEBT, "Liabilities-to-assets",
                    f"Liabilities-to-assets {_pp(cur['liabilities_to_assets'] - prev['liabilities_to_assets'])} ({span})")
            g, g_prev = cur["revenue_growth"], prev["revenue_growth"]
            if _ok(g) and (g < 0 or (_ok(g_prev) and abs(g - g_prev) >= 0.10)):
                add(REVENUE, "Revenue", f"Revenue growth {g * 100:+.1f}% in {p.label}"
                    + (f" vs {g_prev * 100:+.1f}% in {pp.label}" if _ok(g_prev) else ""))
            ig = cur.get("inventory_growth")
            if _ok(ig, g) and abs(ig - g) >= 0.10:
                add(INVENTORY, "Inventory", f"Inventory growth {ig * 100:+.1f}% vs revenue growth {g * 100:+.1f}% ({p.label})")
            cg = cur.get("capex_growth")
            if _ok(cg) and abs(cg) >= 0.25:
                add(CAPEX, "Capital expenditures", f"PP&E capex {cg * 100:+.1f}% ({span})")
    return changes


def _ok(*values) -> bool:
    return all(v is not None and not pd.isna(v) for v in values)


def _big(change, threshold: float) -> bool:
    return _ok(change) and abs(change) >= threshold


def _pp(x: float) -> str:
    return f"{x * 100:+.1f} pp"


def _pct_change(cur: float, prev: float) -> str:
    if prev < 0 < cur or cur < 0 < prev:
        return f"swung from {'a loss' if prev < 0 else 'a profit'} to {'a profit' if cur > 0 else 'a loss'}"
    return f"{(cur / prev - 1) * 100:+.0f}%"


# --- filing retrieval -------------------------------------------------------------------------------

def _current_reports(cik: int, start: date, end: date) -> list[dict]:
    subs = sec_client.submissions(cik)
    blocks = [subs["filings"]["recent"]]
    for extra in subs["filings"].get("files", []):
        if extra.get("filingTo", "9999") >= start.isoformat() and extra.get("filingFrom", "0000") <= end.isoformat():
            blocks.append(sec_client.fetch_json(f"https://data.sec.gov/submissions/{extra['name']}",
                                                f"submissions/{extra['name']}", max_age_hours=24 * 30))
    rows = []
    for block in blocks:
        for i, form in enumerate(block["form"]):
            filed = block["filingDate"][i]
            if form in ("8-K", "8-K/A", "6-K", "6-K/A") and start.isoformat() <= filed <= end.isoformat():
                rows.append({
                    "form": form, "filed": filed, "event_date": block["reportDate"][i] or filed,
                    "accession": block["accessionNumber"][i], "primary": block["primaryDocument"][i],
                    "items": [s.strip() for s in (block.get("items", [""] * len(block["form"]))[i] or "").split(",")
                              if s.strip()],
                })
    return rows


def _priority(row: dict) -> tuple:
    signal = any(i in ITEM_SIGNALS for i in row["items"])
    return (0 if signal else 1, row["filed"])


def _documents(cik: int, row: dict) -> list[tuple[str, str]]:
    """(url, text) for the primary document and press-release exhibits of a current report."""
    acc = row["accession"].replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
    items = sec_client.filing_index(cik, row["accession"])["directory"]["item"]
    sizes = {it["name"]: int(it["size"]) if str(it.get("size", "")).isdigit() else 0 for it in items}
    names = [row["primary"]]
    exhibits = [n for n in sizes if re.search(r"ex-?99|dex99", n, re.I) and n.lower().endswith((".htm", ".html", ".txt"))]
    names += sorted(exhibits)[:MAX_EXHIBITS_PER_FILING]
    docs = []
    for name in dict.fromkeys(names):
        if sizes.get(name, 0) > MAX_DOCUMENT_BYTES:
            continue
        raw = sec_client.filing_file(cik, row["accession"], name)
        docs.append((base + name, _to_text(raw)))
    return docs


def _to_text(raw: bytes) -> str:
    text = raw.decode("utf-8", "ignore")
    text = re.sub(r"(?is)<ix:header>.*?</ix:header>|<script.*?</script>|<style.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text))


# Generic risk-factor and safe-harbor language names every possible event and explains nothing.
_BOILERPLATE = re.compile(r"forward-looking|could cause|risks? and uncertaint|factors (?:that|which) (?:could|may)|"
                          r"no assurance|there can be no|^\(?[ivx]{1,4}\)|"
                          r"table of contents", re.I)


def _is_prose(sentence: str) -> bool:
    """Reject flattened tables and fragments: too many figures or too few words."""
    words = sentence.split()
    numeric = sum(1 for w in words if re.fullmatch(r"[\d$¥%(),.\-–]+", w))
    return len(words) >= 10 and numeric / len(words) <= 0.2 and sentence.count("$") <= 3


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;!?])\s+(?=[A-Z(\"])", text)
    return [s for s in (p.strip() for p in parts)
            if 60 <= len(s) <= 700 and _is_prose(s) and not _BOILERPLATE.search(s)]


# --- scoring --------------------------------------------------------------------------------------

@dataclass
class _Candidate:
    score: float
    sentence: str
    change: SignificantChange
    url: str
    filing_type: str
    event_date: str


def _score_sentence(sentence: str, area: str) -> tuple[float, list[str]]:
    hits = [name for name, rx in _KEYWORD_RES.items() if rx.search(sentence)]
    relevance = sum(1.0 if area in KEYWORDS[h][1] else 0.2 for h in hits)
    return min(relevance, 2.0), hits


def _proximity(event_date: str, start: date, end: date) -> float:
    d = date.fromisoformat(event_date[:10])
    if start <= d <= end:
        return 1.0
    return max(0.0, 1 - (d - end).days / AFTER_PERIOD_DAYS) * 0.8


def _best_in_text(text: str, changes: list[SignificantChange], items: list[str], date_weight: float,
                  annual_note: bool) -> tuple[float, str, SignificantChange] | None:
    best = None
    sentences = _sentences(text)
    for i, sentence in enumerate(sentences):
        # An amount stated in the sentence or the one right after it (e.g. "The charge is about $3 billion.").
        following = sentences[i + 1] if i + 1 < len(sentences) else ""
        amount = 0.7 if _AMOUNT.search(sentence) or _AMOUNT.search(following) else 0.0
        for change in changes:
            relevance, hits = _score_sentence(sentence, change.area)
            if relevance < 1.0:  # needs at least one keyword relevant to the affected area
                continue
            item_bonus = 1.0 if any(i in ITEM_SIGNALS and change.area in ITEM_SIGNALS[i][1] for i in items) else 0.0
            score = relevance + date_weight + amount + item_bonus + (0.5 if annual_note else 0.0)
            if best is None or score > best[0]:
                best = (score, sentence, change)
    return best


def _relevance_label(score: float) -> str:
    return "High" if score >= 3.5 else "Medium" if score >= 2.5 else "Low"


def _trim(sentence: str, limit: int = 320) -> str:
    return sentence if len(sentence) <= limit else sentence[:limit].rsplit(" ", 1)[0] + "..."


def events_for_period(result, company_name: str, year: int, changes: list[SignificantChange]) -> list[Event]:
    cf = next(c for c in result.financials if c.company.name == company_name)
    period = cf.periods[year]
    window_end = period.end + timedelta(days=AFTER_PERIOD_DAYS)
    candidates: list[_Candidate] = []

    reports = [r for r in _current_reports(cf.company.cik, period.start, window_end)
               if r["form"].startswith("6-K") or not r["items"] or set(r["items"]) & _SEARCHED_ITEMS]
    for row in sorted(reports, key=_priority)[:MAX_FILINGS_PER_PERIOD]:
        weight = _proximity(row["event_date"], period.start, period.end)
        for url, text in _documents(cf.company.cik, row):
            best = _best_in_text(text, changes, row["items"], weight, annual_note=False)
            if best:
                label = row["form"] + (f" (Item {', '.join(i for i in row['items'] if i != '9.01')})" if row["items"] else "")
                candidates.append(_Candidate(best[0], best[1], best[2], url, label, row["event_date"]))

    annual = _annual_report(cf, year)
    if annual:
        url, text, form, filed = annual
        for sentence_score in _top_annual_sentences(text, changes):
            score, sentence, change = sentence_score
            candidates.append(_Candidate(score, sentence, change, url, f"{form} (annual report disclosure)", filed))

    events, seen_urls, seen_text = [], set(), set()
    for c in sorted(candidates, key=lambda c: -c.score):
        key = c.sentence[:80].lower()
        if c.url in seen_urls or key in seen_text:
            continue
        seen_urls.add(c.url)
        seen_text.add(key)
        events.append(Event(company_name, year, period.label, c.event_date, c.filing_type, _trim(c.sentence),
                            _relevance_label(c.score), round(c.score, 2), c.change.metric, c.change.description,
                            c.url))
        if len(events) == EVENTS_PER_PERIOD:
            break
    return events


def _annual_report(cf, year: int):
    from financial_analyzer.data import xbrl
    filings = [f for f in xbrl.annual_filings(cf.company.cik, year, year)]
    if not filings:
        return None
    f = filings[0]
    raw = sec_client.filing_file(f.cik, f.accession, f.primary_document)
    return f.url, _to_text(raw), f.form, f.filed


def _top_annual_sentences(text: str, changes: list[SignificantChange], keep: int = 2):
    scored = []
    for sentence in _sentences(text):
        if not _AMOUNT.search(sentence):
            continue  # annual reports are long; keep only disclosures that state an amount
        for change in changes:
            relevance, _ = _score_sentence(sentence, change.area)
            if relevance >= 1.0:
                scored.append((relevance + 0.7 + 0.5 + 0.6, sentence, change))  # amount + note + filed after period
    scored.sort(key=lambda s: -s[0])
    out, seen = [], set()
    for s in scored:
        if s[1][:80] not in seen:
            seen.add(s[1][:80])
            out.append(s)
        if len(out) == keep:
            break
    return out


def attach(result, all_years: bool = False, progress=print) -> None:
    """Find potential explanatory events and store them on the result. Never raises."""
    result.events_run = True
    years = list(result.years) if all_years else [result.latest_year]
    try:
        result.event_changes = detect_changes(result, years)
    except Exception as exc:  # the module must never break the main analysis
        result.event_errors.append(f"Change detection failed: {exc}")
        return
    by_period: dict[tuple[str, int], list[SignificantChange]] = {}
    for change in result.event_changes:
        by_period.setdefault((change.company, change.comparison_year), []).append(change)
    for (company, year), changes in by_period.items():
        progress(f"{company} {changes[0].reported_fiscal_year}")
        try:
            result.events.extend(events_for_period(result, company, year, changes))
        except Exception as exc:
            result.event_errors.append(f"{company} {changes[0].reported_fiscal_year}: event retrieval failed ({exc})")
