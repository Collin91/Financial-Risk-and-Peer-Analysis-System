# Methodology

How the Financial Risk and Peer Analysis System turns SEC filings into a risk score, and what it deliberately
does **not** do.

## 1. Data source

- Annual reports downloaded from SEC EDGAR: **10-K** for U.S. filers, **20-F** for foreign filers such as Toyota.
- Figures are read from each filing's XBRL instance document. Only consolidated (whole-company) facts are used,
  not segment breakdowns.
- When a later filing restates an earlier year, the most recently filed figure is used.
- Every number can be traced to its filing and XBRL concept in the workbook's **Data Lineage** sheet.

## 2. Fiscal years and comparison years

Companies' fiscal years end on different dates. Each company's **reported fiscal year** comes from its own filing
(`dei:DocumentFiscalYearFocus`) and is never changed. Peers are lined up by a separate **comparison year**: the
calendar year containing most of the fiscal period.

| Company | Reported fiscal year | Period ended | Comparison year |
|---|---|---|---|
| Toyota | FY2026 | March 31, 2026 | 2025 |
| Ford | FY2025 | December 31, 2025 | 2025 |
| Tesla | FY2025 | December 31, 2025 | 2025 |
| Walmart | FY2026 | January 31, 2026 | 2025 |
| Target | FY2025 | January 31, 2026 | 2025 |

> Peer comparisons align periods by the calendar year containing most of each company's fiscal period. Reported
> fiscal-year labels and period-end dates are preserved because company fiscal years do not end on the same date.

## 3. Standardization (US GAAP and IFRS)

Each line item has an ordered list of candidate XBRL concepts (for example revenue is `us-gaap:Revenues`,
`us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` or `ifrs-full:Revenue`). The first concept a
company reports is used. Documented derivations fill gaps. For example, Toyota's cost of revenue is total
operating expenses minus SG&A, and this matches its segment-tagged cost of sales exactly.

No company's figures are reclassified. **Capital expenditures** use one definition for everyone: cash paid for
property, plant and equipment. Acquisitions, finance receivables, investments, intangible assets and vehicles bought
for leasing to customers are excluded. If a filer reports only a broader "productive assets" figure and its
intangible assets are material, capex is left missing rather than substituted.

**Currency.** Ratios and growth rates use each company's reporting currency, so yen movements do not distort
Toyota's growth. Dollar amounts use Federal Reserve H.10 rates from FRED: the period average for income and
cash-flow items, and the period-end rate for balance-sheet items.

## 4. Metrics

| Metric | Formula |
|---|---|
| Revenue growth | Revenue / prior-year revenue - 1 |
| Gross margin | (Revenue - cost of revenue) / revenue |
| Operating margin | Operating income / revenue |
| Net margin | Net income attributable to parent / revenue |
| Current ratio | Current assets / current liabilities |
| Liabilities-to-assets | Total liabilities / total assets |
| Return on assets | Net income / average total assets |
| Asset turnover | Revenue / average total assets |
| Free-cash-flow margin | (Reported operating cash flow - PP&E capex) / revenue |
| Capex % of revenue | PP&E capex / revenue |
| Operating cash flow / net income | Reported operating cash flow / net income (not meaningful for losses) |
| Retail extras | Inventory growth, inventory turnover, days inventory outstanding |

## 5. Risk rules and score

Each rule adds its points when triggered. **0-2 points = Lower Risk, 3-5 = Moderate, 6+ = Elevated.**

| Family | Meaning |
|---|---|
| PROF | Profitability rules |
| GROW | Growth rules |
| CASH | Cash-flow and earnings-quality rules |
| LEV | Leverage rules |
| LIQ | Liquidity rules |
| INV | Inventory rules (Retail; days-inventory rule also for Automotive) |

| Rule | Name | Points | Test |
|---|---|---|---|
| PROF-1 | Operating margin decline | 2 | Fell 2.0 pp or more versus the prior period |
| PROF-2 | Gross margin decline | 1 | Fell 2.0 pp or more versus the prior period |
| PROF-3 | Net loss | 2 | Net loss attributable to the parent |
| PROF-4 | Return on assets below peers | 1 | 2.0 pp or more below the peer median (needs 3+ comparable peers) |
| GROW-1 | Revenue decline | 2 | Revenue fell versus the prior period |
| GROW-2 | Revenue growth slowdown | 1 | Growth slowed by 10 pp or more (while still positive) |
| GROW-3 | Capex outpacing revenue | 1 | Capex growth exceeded revenue growth by 10 pp or more |
| CASH-1 | Cash flow diverging from earnings | 3 | Operating cash flow fell while net income rose |
| CASH-2 | Low cash conversion | 2 | Operating cash flow below 0.8x positive net income |
| CASH-3 | Negative free cash flow | 1 | FCF margin at or below -0.50% of revenue |
| CASH-4 | Negative FCF two periods running | 1 | FCF margin at or below -0.50% in this and the prior period |
| LEV-1 | Leverage above peers | 2 | 5.0 pp or more above the peer median (needs 3+ comparable peers) |
| LEV-2 | Rising leverage | 1 | Liabilities-to-assets rose 3.0 pp or more |
| LIQ-1 | Current ratio below 1.0 | 1 | Current ratio below 1.0x |
| LIQ-2 | Falling current ratio | 1 | Fell by 0.20 or more |
| INV-1 | Inventory outpacing sales | 2 | Inventory growth exceeded revenue growth by 5 pp or more |
| INV-2 | Slowing inventory turnover | 1 | Turnover fell 10% or more |
| INV-3 | Rising days of inventory | 1 | Days inventory rose 15 days or more |

**Peer rules** (PROF-4, LEV-1) compare against the median of the *other* companies. They add points only when at least
three peers have usable, comparable values. Otherwise they are shown as *informational*.

## 6. Comparability guards

Some figures cannot be compared fairly across business models or accounting standards. The system shows the
figures unchanged, explains the difference, and stops peer-based points on the affected metrics:

- **Operating cash flow.** Toyota (IFRS) includes changes in finance receivables in operating cash flow. U.S. GAAP
  filers generally classify them in investing activities.
- **Leverage.** Companies with captive-finance arms (Ford Credit, Toyota Financial Services) carry large loan books.
  LEV-1 is not scored when they are compared with companies that have no comparable financing business.
- **Gross margin.** Consolidated gross margins include financing, leasing, energy and service activities in
  different ways, so they are not automotive gross margins.

## 7. Potential explanatory events (optional)

For significant changes (profitability, cash flow, debt, revenue, inventory, capex), the system searches 8-K and 6-K
filings made during or up to 75 days after the period, plus the annual report. It looks for events such as
restructuring, impairments, recalls, acquisitions, litigation, settlements, strikes, plant closures and tariffs.
Candidates are ranked by keyword relevance, date proximity, stated amounts and annual-report disclosure.
**Events are context only.** They never change figures or scores, and a match does not establish causation.

## 8. Limitations

- This is a screening tool. It flags unusual patterns for follow-up; it does not detect fraud, assess management
  intent or predict share prices.
- Accounting-policy differences between US GAAP and IFRS remain even after label matching.
- Thresholds and point values are judgement calls and can be tuned in `financial_analyzer/analysis/risk.py`.
