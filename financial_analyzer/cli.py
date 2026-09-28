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

from financial_analyzer.analysis import pipeline
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


def _show_options(options: list[str]) -> None:
    for i, name in enumerate(options, 1):
        print(f"  {i}. {name}")
    print("  ...or type any company name or ticker (e.g. GM, HMC, AMZN)")


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
        query =options[int(token) - 1] if token.isdigit() and 1 <= int(token) <= len(options) else token
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
    default = "1" if options else ""
    while True:
        answer = _ask("Enter a number, name or ticker", default)
        picked = _resolve_many(answer, options) if answer else None
        if picked and len(picked) == 1:
            print(f"  -> {picked[0].name} ({picked[0].ticker})")
            return picked[0]
        if picked:
            print("  Please choose one company here; you can pick several peers in the next step.")


def _choose_peers(profile: IndustryProfile, target: companies.Company) -> list[companies.Company]:
    options = [n for n in profile.suggested_companies if companies.resolve_ticker_hint(n) != target.ticker]
    print(f"\nStep 3 of 4 - Companies to compare {target.name} with (pick one or more)")
    if options:
        _show_options(options)
    defaults = [n for n in profile.default_companies if n in options][:2] or options[:2]
    default = ",".join(str(options.index(n) + 1) for n in defaults)
    while True:
        answer = _ask("Enter numbers, names or tickers separated by commas", default)
        picked = _resolve_many(answer, options) if answer else None
        if picked:
            peers = [c for c in dict.fromkeys(picked) if c.ticker != target.ticker]
            if peers:
                print(f"  -> {', '.join(f'{c.name} ({c.ticker})' for c in peers)}")
                return peers
        print("  Please choose at least one company other than the one being investigated.")


def _choose_years() -> tuple[int, int]:
    last = date.today().year - 1
    default = f"{last - 4}-{last}"
    print("\nStep 4 of 4 - Years to analyse")
    print("  Comparison years; each company's own fiscal year is shown in the report.")
    while True:
        try:
            return parse_years(_ask("Year range", default))
        except argparse.ArgumentTypeError:
            print("  Please use the form 2021-2025.")


def parse_years(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{4})\s*[-–:]\s*(\d{4})\s*", text)
    if not m or int(m.group(1)) > int(m.group(2)):
        raise argparse.ArgumentTypeError("use the form 2021-2025")
    return int(m.group(1)), int(m.group(2))


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
    peers = [companies.resolve(p) for p in args.peers] if args.peers else _choose_peers(profile, target)
    first_year, last_year = args.years or _choose_years()
    with_events = not args.no_events
    if guided and not args.no_events:
        print()
        with_events = _yes("Also look for SEC filings that may explain big changes? (1-2 min the first time)")

    print(f"\n{RULE}\n{target.name} vs {', '.join(p.name for p in peers)} | {profile.name} | "
          f"{first_year}-{last_year}\n{RULE}")
    if sec_client._user_agent() == sec_client.DEFAULT_USER_AGENT:
        print("Tip: set SEC_USER_AGENT='Your Name you@example.com' to identify yourself to SEC EDGAR.")

    print("Downloading annual reports from SEC EDGAR...")
    result = pipeline.run(target.ticker, [p.ticker for p in peers], profile, first_year, last_year,
                          progress=lambda msg: print(f"  {msg}"))
    if with_events:
        from financial_analyzer import events
        print("Searching SEC filings for possible explanatory events...")
        events.attach(result, all_years=args.event_years == "all", progress=lambda msg: print(f"  {msg}"))

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir = args.out / f"{result.target.lower().replace(' ', '_')}_vs_peers_{stamp}"
    paths = generate_outputs(result, out_dir)
    _print_summary(result)

    print(f"\n{RULE}\nReport folder: {out_dir.resolve()}")
    print(f"  {paths['summary'].name:28} one-page summary (start here)")
    print(f"  {paths['excel'].name:28} full workbook")
    print(f"  {paths['cleaned_csv'].name:28} cleaned financial data")
    if args.open or (guided and sys.stdin.isatty() and _yes("\nOpen the summary page now?")):
        webbrowser.open(paths["summary"].resolve().as_uri())
    return 0
