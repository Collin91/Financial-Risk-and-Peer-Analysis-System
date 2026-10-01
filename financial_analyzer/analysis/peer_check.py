"""Check whether the chosen comparison companies are sensible peers.

Uses each company's SEC industry classification (SIC code) and fiscal year-end from
EDGAR. The check never changes the analysis; it tells the user how well each peer fits
and what the peer group means for scoring, before the run starts and in the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from financial_analyzer.analysis.risk import MIN_PEERS
from financial_analyzer.data import sec_client
from financial_analyzer.data.companies import Company

# SEC SIC divisions (first two digits).
_DIVISIONS = [(1, 9, "agriculture"), (10, 14, "mining"), (15, 17, "construction"), (20, 39, "manufacturing"),
              (40, 49, "transportation and utilities"), (50, 51, "wholesale trade"), (52, 59, "retail trade"),
              (60, 67, "finance, insurance and real estate"), (70, 89, "services"), (91, 99, "public administration")]

SAME, RELATED, SECTOR, DIFFERENT, UNKNOWN = "same industry", "related industry", "same sector", "different sector", "unknown"
GOOD_FITS = (SAME, RELATED)
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def sector_of(sic: str) -> str:
    """SEC division for a SIC code, e.g. '3711' -> 'manufacturing'."""
    if not sic[:2].isdigit():
        return ""
    major = int(sic[:2])
    return next((name for lo, hi, name in _DIVISIONS if lo <= major <= hi), "")


@dataclass(frozen=True)
class IndustryProfile:
    company: Company
    sic: str  # 4-digit SEC industry code, "" if unknown
    industry: str  # SEC description, e.g. "Motor Vehicles & Passenger Car Bodies"
    fiscal_year_end: str  # "MMDD"

    @property
    def year_end_text(self) -> str:
        fye = self.fiscal_year_end
        if len(fye) != 4 or not fye.isdigit() or not 1 <= int(fye[:2]) <= 12:
            return "unknown"
        return f"{_MONTHS[int(fye[:2]) - 1]} {int(fye[2:])}"

    @property
    def sector(self) -> str:
        return sector_of(self.sic)


@dataclass(frozen=True)
class PeerFit:
    profile: IndustryProfile
    match: str  # SAME / RELATED / SECTOR / DIFFERENT / UNKNOWN

    @property
    def ok(self) -> bool:
        return self.match in GOOD_FITS


@dataclass
class PeerCheck:
    target: IndustryProfile
    peers: list[PeerFit]
    notes: list[str] = field(default_factory=list)  # plain-language guidance, most important first

    @property
    def mismatches(self) -> list[PeerFit]:
        return [p for p in self.peers if p.match in (SECTOR, DIFFERENT)]


# SEC shortens words in its industry names ("Apparel & Other Finishd Prods of Fabrics & Similar Matl").
_SIC_WORDS = {"Finishd": "Finished", "Prods": "Products", "Prod": "Products", "Matl": "Materials",
              "Matls": "Materials", "Svcs": "Services", "Mfg": "Manufacturing", "Equip": "Equipment",
              "Eqp": "Equipment", "Instr": "Instruments", "Instrs": "Instruments", "Mach": "Machinery",
              "Bldg": "Building", "Elec": "Electronic", "Misc": "Miscellaneous", "Cos": "Companies",
              "Dev": "Development", "Distr": "Distribution", "Comp": "Computer", "Svc": "Service"}


def tidy_industry(description: str) -> str:
    return " ".join(_SIC_WORDS.get(w, w) for w in description.split())


def profile(company: Company) -> IndustryProfile:
    try:
        subs = sec_client.submissions(company.cik)
    except Exception:  # industry data is a convenience; never block the analysis
        return IndustryProfile(company, "", "", "")
    return IndustryProfile(company, str(subs.get("sic") or ""), tidy_industry(subs.get("sicDescription") or ""),
                           str(subs.get("fiscalYearEnd") or ""))


def classify(target_sic: str, peer_sic: str) -> str:
    if not (target_sic and peer_sic):
        return UNKNOWN
    if target_sic == peer_sic:
        return SAME
    if target_sic[:2] == peer_sic[:2]:
        return RELATED
    sector = sector_of(target_sic)
    return SECTOR if sector and sector == sector_of(peer_sic) else DIFFERENT


def match_label(fit: PeerFit, target: IndustryProfile) -> str:
    """Short explanation of one peer's fit, e.g. 'same industry as Tesla (SIC 3711)'."""
    p = fit.profile
    if fit.match == SAME:
        return f"same industry as {target.company.name} (SIC {p.sic})"
    if fit.match == RELATED:
        return f"related industry: {p.industry} (SIC {p.sic})"
    if fit.match == SECTOR:
        return f"same sector ({p.sector}) but a different industry: {p.industry}"
    if fit.match == DIFFERENT:
        return f"different sector: {p.industry or 'unknown'}"
    return "industry not available from the SEC"


def suggested(names) -> list[Company]:
    """Resolve an industry's suggested company names, skipping any that cannot be found."""
    from financial_analyzer.data import companies
    out = []
    for name in names:
        try:
            out.append(companies.resolve(name))
        except Exception:
            continue
    return out


def check(target: Company, peers: list[Company], suggestions: list[Company] = ()) -> PeerCheck:
    target_profile = profile(target)
    fits = [PeerFit(pr, classify(target_profile.sic, pr.sic)) for pr in (profile(c) for c in peers)]
    result = PeerCheck(target_profile, fits)

    # One note per industry, so two apparel peers share a note instead of repeating it.
    by_industry: dict[str, list[str]] = {}
    for fit in result.mismatches:
        by_industry.setdefault(fit.profile.industry, []).append(fit.profile.company.name)
    for industry, names in by_industry.items():
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        are, its = ("is", "Its") if len(names) == 1 else ("are", "Their")
        result.notes.append(
            f"{who} {are} classified as {industry} by the SEC, not {target_profile.industry}. "
            f"{its} margins and ratios may not be comparable with {target.name}'s.")

    if len(peers) < MIN_PEERS:
        chosen = {c.ticker for c in (target, *peers)}
        # Only suggest companies that would themselves pass the industry check.
        extra = [c.name for c in suggestions
                 if c.ticker not in chosen and classify(target_profile.sic, profile(c).sic) in GOOD_FITS]
        extra = extra[:MIN_PEERS - len(peers) + 1]
        hint = (f" (for example {' or '.join(extra)})" if extra
                else f" from {target.name}'s industry (type any ticker)")
        result.notes.append(
            f"With {len(peers)} peer{'s' if len(peers) != 1 else ''}, rules that compare {target.name} with the peer "
            f"median are shown for information only. Add {MIN_PEERS - len(peers)} more{hint} to score them.")

    ends = {fit.profile.year_end_text for fit in fits} | {target_profile.year_end_text}
    ends.discard("unknown")
    if len(ends) > 1:
        odd = [f"{fit.profile.company.name}'s on {fit.profile.year_end_text}" for fit in fits
               if fit.profile.year_end_text != target_profile.year_end_text]
        result.notes.append(
            f"Fiscal years end on different dates ({target.name}'s on {target_profile.year_end_text}; "
            f"{'; '.join(odd)}). This is handled automatically: each company keeps its own fiscal-year label and "
            f"periods are lined up by comparison year.")
    return result
