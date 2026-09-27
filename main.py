"""Financial Risk and Peer Analysis System.

Examples:
    python main.py --industry automotive --target Tesla --peers Ford Toyota --years 2021-2025
    python main.py --industry retail --target Target --peers Walmart Costco
    python main.py                      # prompts for everything

--years are comparison years: the calendar year containing most of each company's
fiscal period. Each company's own fiscal-year label is always shown alongside
(e.g. Toyota FY2026, year ended March 31, 2026, is in comparison year 2025).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

from financial_analyzer import analysis, sec_client
from financial_analyzer.industries import PROFILES, get_profile
from financial_analyzer.reporting import generate_outputs
from financial_analyzer.risk import stability_notes


def parse_years(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{4})\s*[-–:]\s*(\d{4})\s*", text)
    if not m or int(m.group(1)) > int(m.group(2)):
        raise argparse.ArgumentTypeError("use the form 2021-2025")
    return int(m.group(1)), int(m.group(2))


def prompt_missing(args: argparse.Namespace) -> None:
    if not args.industry:
        choices = ", ".join(p.name for p in PROFILES.values())
        args.industry = input(f"Industry ({choices}) [Automotive]: ").strip() or "Automotive"
    profile = get_profile(args.industry)
    defaults = list(profile.default_companies)
    if not args.target:
        default = defaults[0] if defaults else ""
        args.target = input(f"Company to investigate [{default}]: ").strip() or default
    if not args.peers:
        default = [c for c in defaults if c.lower() != args.target.lower()]
        raw = input(f"Comparison companies, comma-separated [{', '.join(default)}]: ").strip()
        args.peers = [p.strip() for p in raw.split(",") if p.strip()] if raw else default
    if not args.years:
        last = date.today().year - 1
        raw = input(f"Comparison years [{last - 4}-{last}]: ").strip()
        args.years = parse_years(raw) if raw else (last - 4, last)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Financial Risk and Peer Analysis System")
    parser.add_argument("--industry", help=f"one of: {', '.join(p.name for p in PROFILES.values())}")
    parser.add_argument("--target", help="company to investigate (name or ticker)")
    parser.add_argument("--peers", nargs="+", help="comparison companies (names or tickers)")
    parser.add_argument("--years", type=parse_years,
                        help="comparison-year range, e.g. 2021-2025 (calendar year containing most of each fiscal "
                             "period; reported fiscal-year labels are always shown)")
    parser.add_argument("--out", type=Path, default=Path("output"), help="output folder (default: ./output)")
    parser.add_argument("--no-events", action="store_true",
                        help="skip the optional SEC event-context search (Potential Explanatory Events)")
    parser.add_argument("--event-years", choices=["latest", "all"], default="latest",
                        help="search for explanatory events in the latest comparison year only (default) or all")
    args = parser.parse_args(argv)

    prompt_missing(args)
    profile = get_profile(args.industry)
    if not args.peers:
        parser.error("at least one comparison company is required")
    first_year, last_year = args.years

    if sec_client._user_agent() == sec_client.DEFAULT_USER_AGENT:
        print("Note: set SEC_USER_AGENT='Your Name you@example.com' to identify yourself to SEC EDGAR.\n")

    result = analysis.run(args.target, args.peers, profile, first_year, last_year)

    if not args.no_events:
        from financial_analyzer import events
        events.attach(result, all_years=args.event_years == "all")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out / f"{profile.name.lower()}_{result.target.lower().replace(' ', '_')}_{stamp}"
    paths = generate_outputs(result, out_dir)

    year = result.latest_year
    print(f"\n{analysis.PERIOD_DISCLOSURE}")
    print(f"\nRisk summary (comparison year {year})")
    latest = result.scores[result.scores.comparison_year == year].sort_values("score", ascending=False)
    for _, row in latest.iterrows():
        print(f"\n{row.company} {result.period_label(row.company, year)} - {row.risk_level} ({row.score} pts)")
        fired = sorted((r for r in result.rule_results
                        if r.company == row.company and r.comparison_year == year and r.triggered),
                       key=lambda r: -r.points)
        for r in fired:
            print(f"  - {r.detail}  [+{r.points} {r.rule.id} {r.rule.name}]")
        for note in stability_notes(result.metrics, result.rule_results, row.company, year):
            print(f"  - {note}")

    if result.comparability:
        print("\nData-comparability warnings:")
        for w in result.comparability:
            print(f"  - {w.title}")
    if result.warnings:
        print("\nData-quality notes:")
        for w in result.warnings:
            print(f"  - {w}")
    if result.events_run:
        print(f"\nPotential explanatory events: {len(result.events)} found"
              + (f" ({len(result.event_errors)} retrieval note(s))" if result.event_errors else ""))

    print(f"\nOutputs written to {out_dir.resolve()}")
    for label, path in paths.items():
        print(f"  {label:12} {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
