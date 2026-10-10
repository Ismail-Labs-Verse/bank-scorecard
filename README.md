# Who is India's strongest bank?

### An audit-grade scorecard of State Bank of India, HDFC Bank and ICICI Bank, FY2022–FY2026

![Python](https://img.shields.io/badge/Python-3.12-1B2A4A?style=flat-square&logo=python&logoColor=white)
![pandas](https://img.shields.io/badge/pandas-2.x-1B2A4A?style=flat-square&logo=pandas&logoColor=white)
![Tableau](https://img.shields.io/badge/Tableau-Public-D4AF37?style=flat-square&logo=tableau&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-6B7A8F?style=flat-square)

![Overall scorecard score, FY2022-FY2026](outputs/charts/hero_chart.png)

---

## The 5-second summary

- **ICICI Bank leads.** It tops the full FY2022–FY2026 window with a mean score of **66.2**, against **61.1** for HDFC Bank and **27.4** for State Bank of India — and it ranks first in **69.7%** of 10,000 random weightings.
- **SBI is last in every single one.** All 10,000 weightings place SBI third: never first, never second.
- **The lead is conditional, and the condition is measurable.** ICICI holds first place while the asset-quality pillar is weighted above **0.22**; below that, HDFC Bank takes the lead.

---

## The question

> Which of these three banks is strongest on bad loans, profit and efficiency — and does that ranking survive changing the assumptions behind it?

Most comparisons of this kind pick a set of weights, add up the scores and report one winner. The weakness is that the weights are one person's judgement. This study does the same scoring, then re-draws the weights **10,000 times** to measure how often the answer actually changes.

---

## Key findings

- **ICICI Bank tops the FY2022–FY2026 scorecard** with a mean overall score of **66.2**, ahead of HDFC Bank on **61.1** and State Bank of India on **27.4**. The two are strong in different places: ICICI leads on asset quality (**77.9** against 55.7 and 35.8) while HDFC Bank leads on profitability (**65.8** against 55.9 and 20.0).
- **The ranking survives changing the weights.** Drawing pillar weights 10,000 times from a uniform distribution over the weight simplex, ICICI ranks first in **69.7%** of runs and HDFC Bank in **30.3%**. SBI ranks third in **100.0%** of them.
- **One weight can still reverse it.** ICICI keeps the lead for any asset-quality weight above **0.22**; below that, leadership passes to HDFC Bank. Raising the profit pillar above **0.56** does the same. The result therefore rests on how much weight is given to asset quality versus profitability — which is exactly what the sensitivity test exists to expose.
- **The merger-clean window sharpens the picture.** Restricted to FY2024–FY2026, ICICI scores **81.5**, SBI **45.6** and HDFC Bank **35.2** — the same winner, a wider margin, and a different order behind it.

---

## Methodology

- **Primary sources only.** Twenty-one documents — annual reports, quarterly results and investor presentations for all three banks, FY2022–FY2026 — downloaded by hand where the issuers block automated retrieval. Roughly **5,220 pages**.
- **Standalone financials throughout.** Consolidated figures include different subsidiary structures and would compare group shape rather than banking performance.
- **Nothing is scored until it is sourced.** Every one of the **80 rows** in `data/source_log.csv` carries the document, page number, matched line and a SHA-256 of the file it came from.
- **Failure is explicit, not silent.** Values a machine located but a human has not checked are recorded as `auto_extracted` or `ocr_extracted`; a cell that could not be sourced is left blank rather than estimated.
- **Scoring is relative, and says so.** Metrics are oriented so higher is better and normalised 0–100 **within each year** across the three banks, so 100 means *best of these three that year*, never *good in absolute terms*. Pillars are asset quality 35%, profit 40%, efficiency 25% — and those weights are precisely what the sensitivity test probes.

---

## How to reproduce

```bash
conda env create -f environment.yml
conda activate bank-scorecard
python run_all.py
```

`run_all.py` rebuilds every table, chart and export from `data/source_log.csv` and writes `outputs/manifest.json` with a hash of each output.

---

## Repository map

```
src/          extraction, validation, metrics, scoring, sensitivity, charts, exports
tests/        validation and scoring tests (pytest)
data/         raw PDFs (not committed) and the committed source log
outputs/      charts, tables, Tableau exports, run manifest
docs/         understanding guide, case-study memo, source map
tableau/      Tableau Public build guide
```

---

## Data sources

| Source | Used for |
|---|---|
| [SBI investor relations](https://sbi.bank.in/web/investor-relations) | Annual reports FY2022–FY2026, Q1 FY2027 presentation |
| [HDFC Bank investor relations](https://www.hdfcbank.com/personal/about-us/investor-relations/financial-results) | Annual reports FY2022–FY2026, Q1 FY2027 results |
| [ICICI Bank investor relations](https://www.icicibank.com/about-us/investor-relations) | Annual reports FY2022–FY2026, Q1 FY2027 results |
| [RBI DBIE](https://data.rbi.org.in) | System-level benchmarks (context only) |

Raw documents are **not committed** — they are large and remain the copyright of the respective banks. See `data/raw/MANUAL_DOWNLOAD_NEEDED.txt`.

---

## Limitations

- **Extraction is not yet fully verified.** Of the 80 source rows, six ICICI cells remain blank — Gross NPA for all five years and FY2025 return on assets — and the ICICI return figures were read by hand rather than by machine. Automated extraction from annual reports can capture a segment figure or mis-date a multi-year row; `data/source_log.csv` records the page and matched line for every value so each one can be checked. **Treat the specific numbers in this README as provisional until that review is complete.**
- **The HDFC merger.** HDFC Bank absorbed HDFC Ltd on 1 July 2023, so FY2024 contains roughly nine months of the combined entity. Every time series marks it, and the scorecard is reported on both windows.
- **Definitions differ between banks.** Provision coverage, cost-to-income and margin denominators are not defined identically, and are flagged rather than harmonised.
- **Two pillars are thin.** The efficiency pillar has no data for any bank in this dataset, and the profit pillar rests on fewer metrics than intended, which is part of why the ranking moves between windows.
- **Three banks is a small field.** With only three entities, min-max scoring always produces a 0 and a 100, so small real differences look large.
- **CAGR is refused across the merger** by design, because the resulting number would measure the merger rather than the business.

## Disclaimer

This is an educational analysis of publicly available disclosures. It is **not investment advice**, contains **no** buy, sell or hold recommendation on any security, and is not affiliated with or reviewed by any of the institutions named. All financial data belongs to the respective banks and to the Reserve Bank of India and is cited with source. Past figures do not predict future results.
