# Financial Risk and Peer Analysis System

Investigates a company against industry peers using annual financial statements filed with the SEC.
It flags unusual financial patterns that may warrant further investigation, using a transparent,
rule-based score. It does **not** detect fraud or predict share prices.

## Run

```
pip install -r requirements.txt
set SEC_USER_AGENT=Your Name you@example.com        # SEC asks every client to identify itself
python main.py --industry automotive --target Tesla --peers Ford Toyota --years 2021-2025
python main.py --industry retail --target Target --peers Walmart Costco --years 2021-2025
python main.py                                      # prompts for industry, companies and years
```

Options: `--no-events` skips the SEC event search; `--event-years all` searches every year instead of the latest.
Companies can be given by name (see `ALIASES` in `financial_analyzer/companies.py`) or by any SEC ticker.
Downloads are cached in `.cache/`, so re-runs are fast and work offline.

## Fiscal years and comparison years

Each company's **reported fiscal year** comes from its own filing (`dei:DocumentFiscalYearFocus`) and is never
changed. Peers are aligned by a separate **comparison year**: the calendar year containing most of the fiscal period.

| Company | Reported fiscal year | Period ended | Comparison year |
|---|---|---|---|
| Toyota | FY2026 | March 31, 2026 | 2025 |
| Ford | FY2025 | December 31, 2025 | 2025 |
| Tesla | FY2025 | December 31, 2025 | 2025 |

`--years` selects comparison years. Every table, chart and rule result shows the reported fiscal year and period end.

## Pipeline

| Step | Module | What it does |
|---|---|---|
| Download | `sec_client.py`, `xbrl.py` | Finds each 10-K / 20-F on EDGAR and parses its XBRL instance (consolidated facts only; later restatements win) and fiscal-year metadata. |
| Standardize | `standardize.py`, `fx.py` | Maps US GAAP and IFRS concepts onto one set of line items without reclassifying any company's figures. Capex is PP&E purchases only. Converts to USD with Fed H.10 rates (period average for flows, period end for balances). |
| Metrics | `metrics.py` | Revenue growth, gross/operating/net margin, current ratio, liabilities-to-assets, ROA, asset turnover, FCF margin, capex % revenue, OCF / net income, plus inventory metrics. Ratios use reporting currency. |
| Comparability | `comparability.py` | Warns when figures are not directly comparable (IFRS finance-receivable cash flows, captive-finance business models, consolidated gross-margin definitions, capex scope) and blocks peer-based points for those metrics. |
| Flag & score | `risk.py`, `industries.py` | Fixed accounting rules with points (PROF profitability, GROW growth, CASH cash flow, LEV leverage, LIQ liquidity, INV inventory). Peer-based rules need 3+ usable, comparable peers, otherwise they are informational. 0-2 Lower, 3-5 Moderate, 6+ Elevated. |
| Event context | `events.py` | Optional. For significant changes, searches 8-K / 6-K filings and the annual report for potential explanatory events (restructuring, impairment, recall, litigation, ...). Context only: never changes figures or scores. |
| Outputs | `reporting/` | Excel report, HTML risk-summary page, trend charts (PNG), CSVs. |

## Outputs (in `output/<industry>_<target>_<timestamp>/`)

- `financial_risk_report.xlsx`: Risk Summary, Peer Comparison, Metric Trends, Risk Rules (every rule, every period),
  Explanatory Events, Charts, Cleaned Financials, Periods, Data Lineage (XBRL concept, filing and FX rate behind each
  number), Methodology.
- `risk_summary.html`: a self-contained summary page.
- `cleaned_financial_data.csv`, `metrics.csv`, `risk_rule_results.csv`, `explanatory_events.csv`, `charts/*.png`.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

Unit tests use synthetic filings; `tests/test_integration.py` checks real SEC data from the local cache and is skipped
when neither the cache nor the network is available.

## Extending

- **New industry:** add an `IndustryProfile` in `industries.py` (default companies, extra metrics and rules, notes).
- **New rule:** add a `Rule` (with a plain-English name) to `GENERAL_RULES` or `INDUSTRY_RULES` in `risk.py`.
- **Captive-finance company:** add its ticker to `CAPTIVE_FINANCE` in `companies.py`.
- **Unmapped concept:** add it to the candidate list of the relevant `LineItem` in `standardize.py`.
