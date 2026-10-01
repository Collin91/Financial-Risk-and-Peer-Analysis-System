"""Command-line interface.

Run with no arguments for a guided, step-by-step setup, or pass everything as flags:

    python main.py
    python main.py --industry automotive --target Tesla --peers Ford Toyota --years 2021-2025

Years are comparison years: the calendar year containing most of each company's fiscal
period. Each company's own fiscal-year label is always shown alongside (e.g. Toyota
FY2026, year ended March 31, 2026, is in comparison year 2025).
"""

from __future__ import annotations

import argparse
import re
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

from financial_analyzer.analysis import peer_check, pipeline
from financial_analyzer.analysis.industries import PROFILES, IndustryProfile, get_profile
from financial_analyzer.data import companies, sec_client
from financial_analyzer.data.standardize import short_date
from financial_analyzer.reporting import generate_outputs

RULE = "-" * 60


# --- input helpers -------------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def _yes(prompt: str, default: bool = True) -> bool:
    answer = _ask(f"{prompt} ({'Y/n' if default else 'y/N'})").lower()
    return default if not answer else answer.startswith("y")


def _choose_industry() -> IndustryProfile:
    profiles = list(PROFILES.values())
    print("\nStep 1 of 4 - Industry")
    for i, p in enumerate(profiles, 1):
        hint = f"  (e.g. {', '.join(p.suggested_companies[:3])})" if p.suggested_companies else "  (any companies)"
        print(f"  {i}. {p.name}{hint}")
    while True:
        answer = _ask("Choose a number", "1")
        if answer.isdigit() and 1 <= int(answer) <= len(profiles):
            return profiles[int(answer) - 1]
        try:
            return get_profile(answer)
        except ValueError:
            print(f"  Please enter a number from 1 to {len(profiles)}.")


def _show_options(options: list[str], tags: dict[str, str] | None = None,
                  names: dict[str, str] | None = None) -> None:
    """options are names or tickers; names maps a ticker option to the company name shown for it."""
    names = names or {}
    labels = [f"{names.get(n, n)} ({companies.resolve_ticker_hint(n)})" for n in options]
    width = max(len(label) for label in labels)
    for i, (name, label) in enumerate(zip(options, labels), 1):
        tag = (tags or {}).get(name, "")
        print(f"  {i}. {label:<{width}}   {tag}".rstrip())
    print("  ...or type any company name or ticker (e.g. Nike, AMZN)")


def _resolve_many(answer: str, options: list[str]) -> list[companies.Company] | None:
    picked = []
    for token in re.split(r"[,;]", answer):
        token = token.strip()
        if not token:
            continue
        if token.isdigit() and not 1 <= int(token) <= len(options):
            print(f"  Please choose a number from 1 to {len(options)}." if options else
                  "  Please type a company name or ticker.")
            return None
        query = options[int(token) - 1] if token.isdigit() and 1 <= int(token) <= len(options) else token
        try:
            picked.append(companies.resolve(query))
        except ValueError as exc:
            print(f"  {exc}")
            return None
    return picked


def _choose_target(profile: IndustryProfile) -> companies.Company:
    options = list(profile.suggested_companies)
    print("\nStep 2 of 4 - Company to investigate")
    if options:
        _show_options(options)
    else:
        print("  Type a company name or ticker (e.g. Nike, AMZN).")
    default = "1" if options else ""
    while True:
        answer = _ask("Enter a number, name or ticker" if options else "Company name or ticker", default)
        if not answer:
            print("  Please type a company name or ticker.")
            continue
        picked = _resolve_many(answer, options)
        if picked and len(picked) == 1:
            print(f"  -> {picked[0].name} ({picked[0].ticker})")
            return picked[0]
        if picked:
            print("  Please choose one company here; you can pick several peers in the next step.")


_FIT_TAGS = {peer_check.SAME: "same industry", peer_check.RELATED: "related industry",
             peer_check.SECTOR: "different industry", peer_check.DIFFERENT: "different sector",
             peer_check.UNKNOWN: ""}


def print_peer_check(check: peer_check.PeerCheck) -> None:
    t = check.target
    names = [t.company.name] + [f.profile.company.name for f in check.peers]
    width = max(len(n) for n in names) + 2
    print("\nPeer check (SEC industry codes)")
    print(f"        {t.company.name + ' *':<{width}} {t.industry or 'industry unknown'}"
          f"{f' (SIC {t.sic})' if t.sic else ''} - year ends {t.year_end_text}")
    for fit in check.peers:
        mark = "[ok]" if fit.ok else "[?] " if fit.match == peer_check.UNKNOWN else "[!] "
        print(f"  {mark}  {fit.profile.company.name:<{width}} {peer_check.match_label(fit, t)} - year ends "
              f"{fit.profile.year_end_text}")
    print(f"        * = company being investigated")
    for note in check.notes:
        print(f"  Note: {note}")


def _choose_peers(profile: IndustryProfile, target: companies.Company) -> list[companies.Company]:
    options = [n for n in profile.suggested_companies if companies.resolve_ticker_hint(n) != target.ticker]
    names: dict[str, str] = {}
    if options:
        suggestions = peer_check.suggested(options)
    else:  # "Other": suggest the largest companies in the target's SEC industry
        print(f"\nLooking up the largest companies in {companies.possessive(target.name)} SEC industry (first time: up to a minute)...")
        suggestions = peer_check.similar_companies(target, progress=lambda msg: print(f"  {msg}"))
        # Same-industry companies first, then related ones; each group largest first.
        sics = {c.ticker: peer_check.profile(c).sic for c in suggestions}
        target_code = peer_check.profile(target).sic
        suggestions.sort(key=lambda c: sics[c.ticker] != target_code)
        options = [c.ticker for c in suggestions]
        names = {c.ticker: c.name for c in suggestions}
    target_sic = peer_check.profile(target).sic
    by_ticker = {c.ticker: c for c in suggestions}
    tags = {n: _FIT_TAGS[peer_check.classify(target_sic, peer_check.profile(by_ticker[t]).sic)]
            for n in options if (t := companies.resolve_ticker_hint(n)) in by_ticker}
    print(f"\nStep 3 of 4 - Who should {target.name} be compared with?")
    print(f"  Good peers are in the same line of business. Choosing {peer_check.MIN_PEERS} or more also lets the "
          f"peer-median rules add points.")
    if options:
        _show_options(options, tags, names)
    else:
        print(f"  Type company names or tickers separated by commas (e.g. three of {companies.possessive(target.name)} competitors).")
    # Default to enough peers for the peer-median rules to count.
    same = [n for n in options if tags.get(n) == _FIT_TAGS[peer_check.SAME]]
    defaults = [n for n in profile.default_companies if n in options] + same + options
    defaults = list(dict.fromkeys(defaults))[:peer_check.MIN_PEERS]
    default = ",".join(str(options.index(n) + 1) for n in defaults)
    while True:
        answer = _ask("Enter numbers, names or tickers separated by commas" if options else
                      "Company names or tickers, separated by commas", default)
        picked = _resolve_many(answer, options) if answer else []
        if picked is None:  # the problem was already explained
            continue
        peers = [c for c in dict.fromkeys(picked) if c.ticker != target.ticker]
        if not peers:
            print("  Please choose at least one company other than the one being investigated.")
            continue
        check = peer_check.check(target, peers, suggestions)
        print_peer_check(check)
        if check.mismatches:
            if _yes("Some peers are in a different industry. Continue with them anyway?", default=False):
                return peers
        elif _yes("Use these peers?"):
            return peers
        print("  OK - choose the peers again.")


def _choose_years() -> tuple[int, int]:
    last = date.today().year - 1
    default = f"{last - 4}-{last}"
    print("\nStep 4 of 4 - Years to analyze")
    print("  Comparison years; each company's own fiscal year is shown in the report.")
    while True:
        try:
            return parse_years(_ask("Year range", default))
        except argparse.ArgumentTypeError as exc:
            print(f"  Please try again: {exc}.")


def parse_years(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{4})\s*[-–:]\s*(\d{4})\s*", text)
    if not m:
        raise argparse.ArgumentTypeError("use the form 2021-2025")
    first, last = int(m.group(1)), int(m.group(2))
    if first > last:
        raise argparse.ArgumentTypeError(f"the first year must not be after the last (did you mean {last}-{first}?)")
    if last >= date.today().year:
        raise argparse.ArgumentTypeError(f"{last} has no annual reports yet; the latest year available is "
                                         f"{date.today().year - 1}")
    if first < 2010:
        raise argparse.ArgumentTypeError("the SEC's structured (XBRL) data starts around 2010; use 2010 or later")
    return first, last


# --- output --------------------------------------------------------------------------------------

def _print_summary(result) -> None:
    year = result.latest_year
    print(f"\n{RULE}\nResults - comparison year {year}\n{RULE}")
    latest = result.scores[result.scores.comparison_year == year].sort_values("score", ascending=False)
    for _, row in latest.iterrows():
        p = result.period(row.company, year)
        target = " (target)" if row.company == result.target else ""
        print(f"\n{row.company}{target} - {row.risk_level}, {row.score} pt{'' if row.score == 1 else 's'}   "
              f"[{p.label}, year ended {short_date(p.end)}]")
        fired = sorted((r for r in result.rule_results
                        if r.company == row.company and r.comparison_year == year and r.triggered),
                       key=lambda r: -r.points)
        for r in fired[:3]:
            print(f"  - {r.detail.split(' (comparability warning')[0]}")
        if len(fired) > 3:
            print(f"  - ...and {len(fired) - 3} more (see the report)")
        if not fired:
            print("  - No warning signs triggered.")
    notes = []
    if result.comparability:
        notes.append(f"{len(result.comparability)} data-comparability note(s)")
    if result.events_run:
        notes.append(f"{len(result.events)} possible explanatory event(s)")
    if notes:
        print(f"\nAlso in the report: {', '.join(notes)}.")


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except (ValueError, RuntimeError) as exc:  # bad company or industry, no filings, SEC unreachable
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        prog="financial-analyzer",
        description="Financial risk and peer analysis from SEC filings. Run with no options for a guided setup.")
    parser.add_argument("--industry", help=f"one of: {', '.join(p.name for p in PROFILES.values())}")
    parser.add_argument("--target", help="company to investigate (name or ticker)")
    parser.add_argument("--peers", nargs="+", help="companies to compare with (names or tickers)")
    parser.add_argument("--years", type=parse_years, help="comparison-year range, e.g. 2021-2025")
    parser.add_argument("--out", type=Path, default=Path("output"), help="output folder (default: ./output)")
    parser.add_argument("--no-events", action="store_true", help="skip the SEC event search")
    parser.add_argument("--event-years", choices=["latest", "all"], default="latest",
                        help="search for events in the latest comparison year only (default) or all years")
    parser.add_argument("--open", action="store_true", help="open the HTML report when finished")
    args = parser.parse_args(argv)

    guided = not (args.industry and args.target and args.peers and args.years)
    if guided:
        print(f"{RULE}\nFinancial Risk & Peer Analysis\n{RULE}")
        print("Compares a company with its peers using annual reports filed with the SEC.")
    profile = get_profile(args.industry) if args.industry else _choose_industry()
    target = companies.resolve(args.target) if args.target else _choose_target(profile)
    if args.peers:
        # Drop duplicates and the target itself, as the guided setup does.
        peers = [c for c in dict.fromkeys(companies.resolve(p) for p in args.peers) if c.ticker != target.ticker]
        if not peers:
            parser.error("--peers needs at least one company other than the target")
        # Flags mode: show the check but don't ask.
        print_peer_check(peer_check.check(target, peers, peer_check.suggested(profile.suggested_companies)))
    else:
        peers = _choose_peers(profile, target)
    first_year, last_year = args.years or _choose_years()
    with_events = not args.no_events
    if guided and not args.no_events:
        print()
        with_events = _yes("Also look for SEC filings that may explain big changes? (1-2 min the first time)")

    print(f"\n{RULE}\n{target.name} vs {', '.join(p.name for p in peers)} | {profile.name} | "
          f"{first_year}-{last_year}\n{RULE}")
    if sec_client._user_agent() == sec_client.DEFAULT_USER_AGENT:
        example = ('$env:SEC_USER_AGENT = "Your Name you@example.com"' if sys.platform == "win32"
                   else 'export SEC_USER_AGENT="Your Name you@example.com"')
        print(f"Tip: identify yourself to SEC EDGAR before running: {example}")

    print("Downloading annual reports from SEC EDGAR...")
    result = pipeline.run(target.ticker, [p.ticker for p in peers], profile, first_year, last_year,
                          progress=lambda msg: print(f"  {msg}"))
    if with_events:
        from financial_analyzer import events
        print("Searching SEC filings for possible explanatory events...")
        events.attach(result, all_years=args.event_years == "all", progress=lambda msg: print(f"  {msg}"))

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    slug = re.sub(r"[^a-z0-9]+", "_", result.target.lower()).strip("_")
    out_dir = args.out / f"{slug}_vs_peers_{stamp}"
    paths = generate_outputs(result, out_dir)
    _print_summary(result)

    print(f"\n{RULE}\nReport folder: {out_dir.resolve()}")
    print(f"  {paths['summary'].name:28} one-page summary (start here)")
    print(f"  {paths['excel'].name:28} full workbook")
    print(f"  {paths['cleaned_csv'].name:28} cleaned financial data")
    if args.open or (guided and sys.stdin.isatty() and _yes("\nOpen the summary page now?")):
        webbrowser.open(paths["summary"].resolve().as_uri())
    return 0
