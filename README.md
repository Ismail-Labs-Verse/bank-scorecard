# Who is India's strongest bank?

### An audit-grade scorecard of SBI vs HDFC Bank vs ICICI Bank, FY2022–FY2026

![Python](https://img.shields.io/badge/Python-3.12-1B2A4A?style=flat-square&logo=python&logoColor=white)
![pandas](https://img.shields.io/badge/pandas-2.x-1B2A4A?style=flat-square&logo=pandas&logoColor=white)
![Tableau](https://img.shields.io/badge/Tableau-Public-D4AF37?style=flat-square&logo=tableau&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-6B7A8F?style=flat-square)

![Hero Chart](outputs/charts/hero_chart.png)

---

## The 5-second summary

- **ICICI Bank leads the peer group** with a mean overall score of **66.2**, ahead of HDFC Bank on **61.1** and State Bank of India on **27.4** — and it holds first place in **69.7%** of 10,000 randomised weightings.
- **The two leaders are strong in different places.** ICICI Bank wins on asset quality (**77.9** against 55.7 and 35.8); HDFC Bank wins on profitability (**65.8** against 55.9 and 20.0). Which one finishes first therefore depends on how the two pillars are weighted — and that threshold is measured, not asserted.
- **SBI ranks third in every single one of the 10,000 runs.** It is never first and never second under any weighting of the pillars.

---

## Data Verification Status

**This is a preliminary portfolio release. 10 of 80 metrics are human-verified. The remaining metrics are machine-extracted from primary source documents and are pending final verification. A worklist of the 56 pending cells is available in `outputs/tables/missing_data_report.csv`.**

Every value in `data/source_log.csv` carries its document, page number, matched line and a SHA-256 of the file it came from, so each figure can be traced back to a source page and re-checked. Figures drawn from values still pending verification are stamped accordingly in the chart itself.

---

## The question

> **Which of these three banks is strongest on bad loans, profit and efficiency across FY2022–FY2026 — and does that ranking survive changing the assumptions behind it?**

Most comparisons of this kind pick a set of weights, add up the scores and report a single winner. The weakness is that the weights are one person's judgement. This study scores the banks, then re-draws the pillar weights **10,000 times** from a uniform distribution over the weight simplex to measure how often the answer actually changes — turning *"I chose 35/40/25"* into a measurable probability.

---

## Methodology

- **Primary sources only.** Twenty-one documents — annual reports, quarterly results and investor presentations for all three banks across FY2022–FY2026, roughly **5,220 pages** — collected from the banks' own investor-relations channels, by hand where issuers block automated retrieval.
- **Standalone financials throughout.** Consolidated figures blend differing subsidiary structures and would compare group shape rather than banking performance, so every metric is taken on the standalone basis.
- **Scoring is relative, by construction.** Metrics are oriented so higher is better, then normalised 0–100 **within each financial year** across the three banks. A score of 100 means *best of these three that year*, never *good in absolute terms* — and no score is published without its raw value alongside.
- **Assumption risk is measured, not assumed away.** The 10,000-draw sensitivity test reports the probability of each bank finishing first, second and third, plus the exact weight at which leadership changes hands. A verdict is only described as stable if it holds on both the full window and a merger-clean one.
- **The HDFC Ltd merger is handled structurally.** The merger completed on 1 July 2023, so FY2024 contains roughly nine months of the combined entity. Every time series marks it with a dotted line, CAGR refuses to cross it, and the scorecard is computed on both FY2022–FY2026 and FY2024–FY2026.

---

## Key Findings

- **ICICI Bank leads the FY2022–FY2026 scorecard** with a mean overall score of **66.2**, ahead of HDFC Bank on **61.1** and State Bank of India on **27.4**.
- **The ranking is robust to reasonable disagreement about weights.** Across 10,000 random weightings, ICICI Bank ranks first in **69.7%** of runs and HDFC Bank in **30.3%**. State Bank of India ranks third in **100.0%** of them.
- **One weight reverses the result, and the threshold is known.** ICICI Bank holds first place while the asset-quality pillar is weighted above **0.22**; below that HDFC Bank takes the lead. Raising the profit pillar above **0.56** does the same, so the outcome rests on the balance struck between asset quality and profitability.
- **The merger-clean window sharpens the picture.** Restricted to FY2024–FY2026, ICICI Bank scores **81.5**, State Bank of India **45.6** and HDFC Bank **35.2** — the same winner, a wider margin, and a different order behind it.

---

## Visual gallery

![Sensitivity Chart](outputs/charts/sensitivity_chart.png)

*How often each bank finishes first across 10,000 randomised pillar weightings.*

![Asset Quality Pillar](outputs/charts/pillar_asset_quality.png)

![Profitability Pillar](outputs/charts/pillar_profit.png)

*Pillar scores are computed within each year, so the three banks span 0 to 100 in every period.*

---

## How to reproduce

```bash
conda env create -f environment.yml
conda activate bank-scorecard
python run_all.py
```

`run_all.py` rebuilds every table, chart and export from `data/source_log.csv`, and writes `outputs/manifest.json` with a SHA-256 of each output. Running `python run_all.py` without arguments scores only human-verified values and prints the worklist of pending cells instead of a ranking; the published figures are reproduced with `python run_all.py --provisional`.

---

## Repository map

```
src/          extraction, validation, metrics, scoring, sensitivity, charts, exports
tests/        38 tests covering the validation rules and the scoring mathematics
data/         raw source PDFs (never committed) and the committed source log
outputs/      charts, tables, Tableau exports, verification worklist, run manifest
docs/         understanding guide, case-study memo, investor-relations source map
tableau/      Tableau Public build guide
```

## Data sources

| Source | Used for |
|---|---|
| [SBI investor relations](https://sbi.bank.in/web/investor-relations) | Annual reports FY2022–FY2026, Q1 FY2027 presentation |
| [HDFC Bank investor relations](https://www.hdfcbank.com/personal/about-us/investor-relations/financial-results) | Annual reports FY2022–FY2026, Q1 FY2027 results |
| [ICICI Bank investor relations](https://www.icicibank.com/about-us/investor-relations) | Annual reports FY2022–FY2026, Q1 FY2027 results |
| [RBI DBIE](https://data.rbi.org.in) | System-level benchmarks (context only) |

Raw documents are not committed — they are large and remain the copyright of the respective banks and of the Reserve Bank of India.

---

## Scope and limitations

- **This version focuses on Asset Quality and Profitability. The Efficiency pillar is scoped for a future release pending consistent standardised disclosures across all peer banks.** Its 25% weighting is therefore not applied; the remaining pillar weights are renormalised proportionally and identically for every bank, and each scored row records the pillars used.
- **Certain ICICI metrics were left out due to a lack of secondary verification sources, adhering to a strict no-guesswork policy.**
- **The 0–100 scale represents a relative ranking within this 3-bank peer group, not an absolute score.**
- **The HDFC Ltd merger (July 2023) introduces a structural break. Pre-merger and post-merger figures are treated as distinct regimes**, and a verdict is only considered stable if it survives both windows.
- **Ratio definitions are not identical across the three banks.** Where a bank reports a variant — a core cost-to-income ratio, or a provision coverage figure including technical write-offs — the difference is flagged in the source log rather than smoothed away.

## Disclaimer

This is an educational analysis of publicly available disclosures. It is **not investment advice** and contains **no** buy, sell or hold recommendation on any security. It is not affiliated with, endorsed by, or reviewed by any of the institutions named. All financial data belongs to the respective banks and to the Reserve Bank of India and is cited with source. Past figures do not predict future results.
