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

Companies can be given by name (see `ALIASES` in `financial_analyzer/companies.py`) or by any SEC ticker.
Downloads are cached in `.cache/`, so re-runs are fast and work offline.

## Pipeline

| Step | Module | What it does |
|---|---|---|
| Download | `sec_client.py`, `xbrl.py` | Finds each 10-K / 20-F on EDGAR and parses its XBRL instance (consolidated facts only; later restatements win). |
| Standardize | `standardize.py`, `fx.py` | Maps US GAAP and IFRS concepts onto one set of line items, with documented derivations. Converts to USD with Fed H.10 rates (period average for flows, period end for balances). Fiscal years ending Jan-May are labelled with the prior calendar year. |
| Metrics | `metrics.py` | Revenue growth, gross/operating/net margin, current ratio, debt-to-assets, ROA, asset turnover, FCF margin, capex % revenue, OCF / net income, plus inventory metrics. Ratios use reporting currency so FX moves don't distort them. |
| Compare | `analysis.py` | Peer comparison (vs. median of the other companies) and target vs. its own history. |
| Flag & score | `risk.py`, `industries.py` | Fixed accounting rules, each worth set points. 0-2 Lower, 3-5 Moderate, 6+ Elevated. Industry profiles add rules (Retail: inventory growth vs. sales, inventory turnover, days inventory). |
| Outputs | `reporting/` | Excel report, HTML risk-summary page, trend charts (PNG), cleaned-data / metrics / rule-result CSVs. |

## Outputs (in `output/<industry>_<target>_<timestamp>/`)

- `financial_risk_report.xlsx`: Risk Summary, Peer Comparison, Metric Trends, Risk Rules (every rule, every year),
  Charts, Cleaned Financials, Data Lineage (the XBRL concept, filing and FX rate behind each number), Methodology.
- `risk_summary.html`: a self-contained summary page.
- `cleaned_financial_data.csv`, `metrics.csv`, `risk_rule_results.csv`, `charts/*.png`.

## Extending

- **New industry:** add an `IndustryProfile` in `industries.py` (default companies, extra metrics and rules, caveats).
- **New rule:** add a `Rule` to `GENERAL_RULES` or `INDUSTRY_RULES` in `risk.py`. It returns `(triggered, detail)`, or `None` when data is missing.
- **Unmapped concept:** add it to the candidate list of the relevant `LineItem` in `standardize.py`.
