"""Check whether the chosen comparison companies are sensible peers.

Uses each company's SEC industry classification (SIC code) and fiscal year-end from
EDGAR. The check never changes the analysis; it tells the user how well each peer fits
and what the peer group means for scoring, before the run starts and in the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from financial_analyzer.analysis.risk import MIN_PEERS
from financial_analyzer.data import sec_client
from financial_analyzer.data.companies import Company, possessive

# SEC SIC divisions (first two digits).
_DIVISIONS = [(1, 9, "agriculture"), (10, 14, "mining"), (15, 17, "construction"), (20, 39, "manufacturing"),
              (40, 49, "transportation and utilities"), (50, 51, "wholesale trade"), (52, 59, "retail trade"),
              (60, 67, "finance, insurance and real estate"), (70, 89, "services"), (91, 99, "public administration")]

# Industries the SEC codes far apart that compete directly, so they are treated as related.
# Nike is "Rubber & Plastics Footwear" (3021) while Under Armour and Lululemon are apparel (23xx).
RELATED_GROUPS = {
    "apparel and footwear": [(2300, 2399), (3020, 3021), (3140, 3149)],
    # Walmart, Target and Costco (variety stores, 5331) compete directly with Kroger (grocery, 5411).
    "general merchandise and grocery": [(5300, 5399), (5410, 5412)],
}
# The SEC codes actually in use inside each group, searched when suggesting peers.
RELATED_GROUP_CODES = {
    "apparel and footwear": ("3021", "2300", "2320", "2330", "2340", "2390", "3140"),
    "general merchandise and grocery": ("5331", "5311", "5399", "5411", "5412"),
}

FINANCE_SECTOR = "finance, insurance and real estate"
FINANCIAL_WARNING = (
    "{names} {verb} a bank, insurer, real-estate firm or other financial company. This tool's ratios are built for companies that "
    "make or sell things: financial companies have no gross margin or current ratio in the usual sense, and their "
    "operating cash flow swings with lending and trading. Treat the scores and cash-flow flags as unreliable.")

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
    def financial_companies(self) -> list[str]:
        """Banks, insurers and other finance companies, whose statements don't fit the ratios used here."""
        return [p.company.name for p in [self.target, *(f.profile for f in self.peers)]
                if p.sector == FINANCE_SECTOR]

    @property
    def mismatches(self) -> list[PeerFit]:
        return [p for p in self.peers if p.match in (SECTOR, DIFFERENT)]


# SEC shortens words in its industry names ("Apparel & Other Finishd Prods of Fabrics & Similar Matl").
_SIC_WORDS = {"Finishd": "Finished", "Prods": "Products", "Prod": "Products", "Matl": "Materials",
              "Matls": "Materials", "Svcs": "Services", "Mfg": "Manufacturing", "Equip": "Equipment",
              "Eqp": "Equipment", "Instr": "Instruments", "Instrs": "Instruments", "Mach": "Machinery",
              "Bldg": "Building", "Elec": "Electronic", "Misc": "Miscellaneous", "Cos": "Companies",
              "Dev": "Development", "Distr": "Distribution", "Comp": "Computer", "Svc": "Service",
              "Furnishgs": "Furnishings", "Clothg": "Clothing", "Prep": "Preparations", "Pharm": "Pharmaceutical"}


def tidy_industry(description: str) -> str:
    def expand(word: str) -> str:
        core = word.rstrip(",;")
        return _SIC_WORDS.get(core, core) + word[len(core):]
    return " ".join(expand(w) for w in description.split())


def profile(company: Company) -> IndustryProfile:
    try:
        subs = sec_client.submissions(company.cik)
    except Exception:  # industry data is a convenience; never block the analysis
        return IndustryProfile(company, "", "", "")
    return IndustryProfile(company, str(subs.get("sic") or ""), tidy_industry(subs.get("sicDescription") or ""),
                           str(subs.get("fiscalYearEnd") or ""))


def related_group(sic: str) -> str:
    if not sic.isdigit():
        return ""
    return next((name for name, ranges in RELATED_GROUPS.items()
                 if any(lo <= int(sic) <= hi for lo, hi in ranges)), "")


def classify(target_sic: str, peer_sic: str) -> str:
    if not (target_sic and peer_sic):
        return UNKNOWN
    if target_sic == peer_sic:
        return SAME
    if target_sic[:2] == peer_sic[:2] or (related_group(target_sic) and
                                          related_group(target_sic) == related_group(peer_sic)):
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


# Peer suggestions come from roughly the largest listed companies only, which keeps out shells and
# tiny registrants that happen to share an industry code.
SUGGESTION_MAX_RANK = 4000


def similar_companies(target: Company, limit: int = 8, progress=None) -> list[Company]:
    """The largest listed companies with the target's SEC industry code (or a related one), biggest first.

    SEC's ticker file lists companies roughly by market value, so its order ranks the matches.
    Returns [] when the industry is unknown or SEC can't be reached.
    """
    from financial_analyzer.data import companies
    try:
        sic = profile(target).sic
        if not sic:
            return []
        codes = dict.fromkeys([sic, *RELATED_GROUP_CODES.get(related_group(sic), ())])
        in_industry = {cik for code in codes for cik in sec_client.companies_in_sic(code, progress)}
        out, seen = [], {target.cik}
        for rank, entry in enumerate(sec_client.company_tickers().values()):
            if rank >= SUGGESTION_MAX_RANK:
                break
            cik = int(entry["cik_str"])
            if cik in in_industry and cik not in seen:
                seen.add(cik)  # a company can have several tickers (share classes); keep the first, most traded
                out.append(companies.to_company(entry))
                if len(out) == limit:
                    break
        return out
    except Exception:  # suggestions are a convenience; never block the analysis
        return []


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
    if fin := result.financial_companies:
        names = fin[0] if len(fin) == 1 else ", ".join(fin[:-1]) + " and " + fin[-1]
        result.notes.append(FINANCIAL_WARNING.format(names=names, verb="is" if len(fin) == 1 else "are each"))

    # One note per industry, so two apparel peers share a note instead of repeating it.
    by_industry: dict[str, list[str]] = {}
    for fit in result.mismatches:
        by_industry.setdefault(fit.profile.industry, []).append(fit.profile.company.name)
    for industry, names in by_industry.items():
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        are, its = ("is", "Its") if len(names) == 1 else ("are", "Their")
        result.notes.append(
            f"{who} {are} classified as {industry} by the SEC, not {target_profile.industry}. "
            f"{its} margins and ratios may not be comparable with {possessive(target.name)}.")

    if len(peers) < MIN_PEERS:
        chosen = {c.ticker for c in (target, *peers)}
        # Only suggest companies that would themselves pass the industry check.
        extra = [c.name for c in suggestions
                 if c.ticker not in chosen and classify(target_profile.sic, profile(c).sic) in GOOD_FITS]
        extra = extra[:MIN_PEERS - len(peers) + 1]
        hint = (f" (for example {' or '.join(extra)})" if extra
                else f" from {possessive(target.name)} industry (type any ticker)")
        result.notes.append(
            f"With {len(peers)} peer{'s' if len(peers) != 1 else ''}, rules that compare {target.name} with the peer "
            f"median are shown for information only. Add {MIN_PEERS - len(peers)} more{hint} to score them.")

    ends = {fit.profile.year_end_text for fit in fits} | {target_profile.year_end_text}
    ends.discard("unknown")
    if len(ends) > 1:
        odd = [f"{possessive(fit.profile.company.name)} on {fit.profile.year_end_text}" for fit in fits
               if fit.profile.year_end_text != target_profile.year_end_text]
        result.notes.append(
            f"Fiscal years end on different dates ({possessive(target.name)} on {target_profile.year_end_text}; "
            f"{'; '.join(odd)}). This is handled automatically: each company keeps its own fiscal-year label and "
            f"periods are lined up by comparison year.")
    return result
