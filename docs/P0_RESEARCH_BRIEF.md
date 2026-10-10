# P0 - Research Brief, Definitions and Audit of the Original Brief

Date: 2026-10-10
Status: Phase P0 deliverable. This document contains **no financial data**. It is the
set of rules the project will obey, plus the list of things that were wrong or missing in
the original brief. No number appears here because no number has been verified yet.

---

## 0. What this project will and will not claim

**Will claim:** a ranking of SBI, HDFC Bank and ICICI Bank on bad loans, profit and
efficiency for FY2022-FY2026, on a stated basis, from cited primary documents, with a
measured statement of how stable that ranking is when the assumptions change.

**Will not claim:** that any bank is a good or bad investment; that a score of 100 means
"good in absolute terms" (it means "best of these three that year"); that the numbers are
audited by anyone other than the banks themselves.

---

## 1. Audit of the original brief

Ten findings, worst first. Each one is either a defect that would break the project, or a
gap that must be filled before code is written.

### BLOCKER 1 - `run_all.py` cannot rebuild from raw, by design

Rule 9 asks for one command that rebuilds everything **from raw data**, plus a SHA-256
hash log of every raw input. But the publishing rules also say `data/raw/` is never
committed (copyright and size). A fresh clone therefore has no raw files and the
"reproduce in 3 commands" promise fails for the exact audience the repo is built for.

**Fix - a two-tier contract.**
- `python run_all.py` rebuilds every table, chart and PDF from `data/processed/`, which
  **is** committed. Verified numbers of the run are written to `outputs/manifest.json`.
- `python run_all.py --verify-raw` additionally re-hashes `data/raw/` against the source
  log when the raw files are present locally, and reports any file that changed.
- `python run_all.py --fetch` re-downloads whatever the source log says is fetchable.
- The README states plainly which tier a fresh clone can run.

### BLOCKER 2 - the scorecard normalisation rule is under-specified and misleading

The brief says min-max **"across the three banks and all years"**. With 3 banks x 5 years
that is 15 observations per metric, and the pool is recomputed every time. Two bad
consequences: (a) a bank can improve every single year and still watch its score fall,
because the other banks moved; (b) the score silently becomes "relative to these 15
observations", which is not what a reader assumes "78/100" means.

**Fix.** Min-max **within each financial year, across the three banks**. Scores then
measure "who was best that year" and are comparable year to year. The all-years pool is
kept as a robustness panel, clearly labelled. This is stated on every chart.

### BLOCKER 3 - absolute size must never be scored

"Net profit" and "NII" are specified as metrics in INR crore. Scored by min-max, they
measure **size**, not strength: SBI standalone is a multiple of the other two, so the
ranking would simply reproduce a size ordering. That would be a meaningless result dressed
up as analysis.

**Fix.** Only ratios and growth rates enter the scorecard. Currency levels are reported in
tables and dashboards but never scored. A unit test enforces this: no metric with unit
`INR_crore` may be marked score-eligible.

### BLOCKER 4 - Q1 FY27 must not be pooled with annual data

A quarter's profit, NII and provisions are 3-month flows. Pooling a 3-month figure with
12-month figures inside one min-max range corrupts the normalisation for every bank.

**Fix.** The scorecard is annual only (FY2022-FY2026). Q1 FY2027 is a separate
"latest snapshot" panel using **ratios only**, explicitly labelled as excluded from the
score, and compared year-on-year against Q1 FY2026 (not against full-year FY2026).

### BLOCKER 5 - "no negative ratios" as a hard stop will reject correct data

Profit growth, NII growth and credit cost can all be legitimately negative, and a bank can
report a net write-back. A hard stop on negative values would fire on good data, and the
predictable outcome is that the check gets weakened to make the pipeline run.

**Fix.** Split the checks. **Hard fail** only on impossible values: Net NPA > Gross NPA,
negative NPA or NIM, PCR below 0, a missing year. **Warn** on plausible-but-notable values:
any negative growth rate, PCR above 100 (a bank that includes technical write-offs will
legitimately exceed 100 - this is a definition question, not an error), ROA outside
-1% to +3%.

### BLOCKER 6 - "profit = income minus expenses" is not a defined identity for a bank

The brief's sanity check is not computable as written. Banks have a specific P&L ladder.

**Fix - check the actual ladder, with a stated tolerance:**
```
Operating profit = Net interest income + Other income - Operating expenses
Profit before tax = Operating profit - Provisions and contingencies (+/- exceptional items)
Net profit       = Profit before tax - Tax expense
```
Tolerance: the larger of +/- 0.5% of net profit or +/- INR 25 crore. Two reasons for a
tolerance rather than exact equality: banks report in whole INR crore, and "exceptional"
and "prior period" items sit outside the main ladder. A failure is reported with the exact
line items that do not tie.

### BLOCKER 7 - the two-source rule as written is weaker than it looks, and sometimes impossible

"Confirmed in 2 different documents" - but a bank's annual report and that same bank's
Pillar 3 disclosure are the same issuer reporting the same audited numbers. That is a
**consistency** check, not independent confirmation, and it should not be described as
stronger evidence than it is.

**Fix.** Every data point records a `verification_method`:
- `recomputed` - derived from raw components (strongest),
- `cross_issuer` - confirmed by an independent publisher (e.g. a system-level RBI figure),
- `same_issuer_2_docs` - consistent across two documents from the same bank (normal case),
- `single_source` - one source only.
And a route must exist for metrics that only ever appear in one document (slippage ratio
and credit cost are the likely cases): a single primary source **plus** a recomputation from
its own components satisfies the rule. Without this escape hatch the rule is unachievable
and the temptation is to invent the second source.

### BLOCKER 8 - the Tableau assumption is wrong for this machine

Verified on 2026-10-10: **Tableau Public (Apple silicon) is installed. Tableau Desktop is
not installed.** These are different products and the instructions must match the one that
actually exists. Tableau Public is free and sufficient for a portfolio workbook, but the
build guide must be written against its feature set, and the exact limits (local extract
handling, saving, publishing) will be verified in P4 rather than assumed now.

Related: exporting a `.hyper` extract needs `tableauhyperapi`, which is deliberately kept
out of `environment.yml` until it is proven to install cleanly. The pipeline ships CSV
output as the guaranteed path; `.hyper` is a bonus, not a dependency.

### BLOCKER 9 - `environment.yml` via `conda env export` would break reproducibility

`conda env export` dumps whichever environment is active. Applied to Anaconda **base** it
produces a ~574-line file with about 500 packages, platform-specific build strings and a
`prefix:` line pointing at `/opt/anaconda3`. That file cannot rebuild this project, and it
hides which packages the project actually depends on.

**Fix.** `environment.yml` is hand-written and declares only the real dependency set.
The exact resolved versions get frozen into a lock file **after** the first successful
environment solve. The base snapshot is kept separately as `environment-lock.yml`, clearly
labelled as an audit trail and **not** the project environment.

Related machine fact: base is Python 3.14.6. Python 3.14 does not yet have wide
Apple-Silicon wheel coverage for the scientific stack, so the project environment pins
**Python 3.12** instead.

### BLOCKER 10 - byte-identical rebuilds are not achievable for PDFs

Rule 9 wants running twice to give identical output. PDF writers stamp a creation date into
the file, so a byte-hash test over generated PDFs fails on a correct pipeline.

**Fix.** Freeze the timestamp in generated PDFs (`SOURCE_DATE_EPOCH` and explicit
document metadata) so they are reproducible too. The determinism test then hashes CSVs and
PNGs byte-for-byte, and compares PDFs by extracted text content. Both are real tests.

---

## 2. Gaps in the brief that must be filled before P2

| # | Gap | Decision |
|---|---|---|
| 1 | "FY24 onwards not comparable" is too coarse | FY2024 is itself a **stub period**: HDFC Ltd merged into HDFC Bank effective 1 July 2023, so FY2024 contains roughly 9 months of the combined operation, and the opening balance sheet was restated from the merger date. Treat FY2022-FY2023 (pre-merger), FY2024 (transition), FY2025-FY2026 (post-merger) as **three regimes**, and never draw a single CAGR across them. |
| 2 | No rounding or unit policy | Store values exactly as the bank reports them, in the bank's own unit, with the unit in the row. Convert for display only. Never round intermediates. 1 crore = 10 million = 0.01 billion; 1 lakh crore = 1,000 billion. Ratios are stored as percentages with the precision the bank published. |
| 3 | No licence decision | Code: MIT. Written analysis and the project's own tables: CC BY 4.0. The underlying data belongs to the banks and the RBI and cannot be re-licensed - the repository states that it is cited for non-commercial educational use. |
| 4 | No rule for restated comparatives | Banks restate prior-year comparatives after mergers or accounting changes. Store the original and the restated value as **two rows** with different `source_id`s, and let the pipeline prefer the restated value with a flag. Otherwise this shows up later as a mysterious "source conflict". |
| 5 | No single source of truth for bank colours | Charts, Tableau and the PDFs will drift apart. Fix: one `src/tokens.py` (or YAML) holding the three bank colours, the grey scale and the type scale. Also: colour must never be the only carrier of meaning - always pair with a label or marker shape, and check contrast. |
| 6 | "No cherry-picking" needs a mechanism | Every chart commit states what it shows against the story, and the memo carries a mandatory "what argues against this conclusion" section, produced by the sensitivity test rather than by memory. |
| 7 | The 2026 research questions have no data trail | Add `data/processed/macro_events.csv`: repo-rate change dates and basis points, the merger effective date, RBI circular dates, each with a source. Every chart annotation is drawn from this file, so no annotation is unsourced. |
| 8 | RBI benchmark availability is assumed | RBI publications lag. The Report on Trend and Progress of Banking in India for FY2026 may simply not exist yet. The rule: use the newest **published** year and label it, never back-fill it from a news article. |
| 9 | No per-phase definition of done | See section 7. |
| 10 | No falsification condition | The memo must state the exact condition that flips the verdict (for example "the ranking changes if asset-quality weight exceeds X%"), which the sensitivity test produces as a number, not as an opinion. |

---

## 3. Metric dictionary

Rules for every metric: one-line meaning for a non-specialist; the exact formula; the
direction that counts as good; and the trap. Direction drives scoring: `+1` means higher
is better.

### Bad loans (asset quality)

| Metric | One-line meaning | Formula | Good | The trap |
|---|---|---|---|---|
| Gross NPA % | Share of the loan book that has stopped paying | Gross NPAs / Gross advances x 100 | lower (+0? see note) | Denominator is **gross advances**, not total assets. Check whether foreign-office advances are included. |
| Net NPA % | Bad loans left after setting money aside for them | Net NPAs / Net advances x 100 | lower | Net NPAs = Gross NPAs - provisions held against them. Net advances = gross advances - those provisions. |
| Provision Coverage Ratio | How much of the bad loan pile is already provided for | Provisions on NPAs / Gross NPAs x 100 | higher | Banks differ on whether **technical write-offs** go in the numerator; that alone can push PCR past 100%. Use one convention or flag it. |
| Slippage ratio | How fast good loans are turning bad | Fresh NPAs in the period / standard advances at the start x 100 | lower | Rarely disclosed directly. Often must be read off an investor presentation, and may be **UNVERIFIED** for some bank-years. |
| Credit cost | What bad loans cost the bank in the period | Provisions and write-offs / average advances x 100 | lower | Both the denominator (average advances vs average assets) and whether write-offs are included vary by bank. |

### Profit

| Metric | One-line meaning | Formula | Good | The trap |
|---|---|---|---|---|
| Net profit | Bottom line after provisions and tax | see the P&L ladder in BLOCKER 6 | higher | A currency level - **not scored** (BLOCKER 3). |
| Net interest income (NII) | Interest earned minus interest paid | Interest earned - interest expended | higher | A currency level - **not scored**. |
| Net interest margin (NIM) | How profitable the loan book is per rupee | NII / average interest-earning assets x 100 | higher | The denominator varies (average working funds vs average earning assets). Pin the definition to what each bank discloses and flag differences. |
| Return on assets (ROA) | Profit per rupee of assets | Net profit / average total assets x 100 | higher | Some banks use period-end assets, others averages. Check the note to the accounts. |
| Return on equity (ROE) | Profit per rupee of shareholders' money | Net profit / average equity x 100 | higher | Depends heavily on leverage - this is exactly what the DuPont step decomposes. |
| Profit growth | Year-on-year change in net profit | (PAT_t / PAT_t-1 - 1) x 100 | higher | **Can be negative.** Low-base distortions, and FY2024 for HDFC is not comparable. |

### Efficiency

| Metric | One-line meaning | Formula | Good | The trap |
|---|---|---|---|---|
| Cost-to-income ratio | Cost of running the bank per rupee of income | Operating expenses / (NII + other income) x 100 | **lower** | HDFC reports a *core* cost-to-income ratio. If that is what the others do not do, the numbers are not comparable - flag, do not smooth. |
| Operating expense ratio | Cost per rupee of assets | Operating expenses / average total assets x 100 | lower | Sterling proxy for efficiency, and less definition-sensitive. |
| Non-interest income share | How much income comes from fees and treasury, not lending | Other income / total income x 100 | **no clear direction** | Treasury gains are volatile and flatter the ratio in a good market. Handled as context, not as a scored metric, unless the evidence says otherwise. |

### Safety

| Metric | One-line meaning | Formula | Good | The trap |
|---|---|---|---|---|
| CRAR | Capital held against risk-weighted assets | Total capital / RWA x 100 | higher | Basel III definition; check whether the figure is the bank-level or group-level one. |
| CET1 ratio | The highest-quality part of that capital | CET1 capital / RWA x 100 | higher | Same as above; regulatory minimums changed over the period. |

### System benchmarks (RBI)

Three system-wide numbers for context: system gross NPA ratio, system credit growth and
system deposit growth for scheduled commercial banks. Sourced from RBI publications and
stored like any other series, with the newest published year labelled.

---

## 4. Comparability map

| Period | Regime | Note |
|---|---|---|
| FY2022, FY2023 | Pre-merger HDFC Bank | Comparable for all three banks |
| FY2024 | Merger transition | HDFC has roughly 9 months of combined operations. Not comparable to either side. |
| FY2025, FY2026 | Post-merger | Comparable for all three banks |
| Q1 FY2027 | Snapshot | Ratios only. Excluded from the score. |

The HDFC merger date is **1 July 2023** per the original brief; it will be confirmed
against a primary source (the annual report's merger note) in P2 rather than repeated on
trust. Every chart carries the merger line, and every scorecard test is run on both
FY2022-FY2026 and FY2024-FY2026.

---

## 5. Exact scoring formula

For metric `m` in financial year `y`, over the three banks `b`:

```
d_m      = +1 if higher is better, -1 if lower is better
t(b)     = d_m * x(b)                                  # orient so higher = better
raw      = (t(b) - min t) / (max t - min t)
S_m(b)   = 100 * raw
edge case: if max t == min t, then S_m(b) = 50 for all three, flagged as degenerate
pillar P = sum over metrics in P of (w_m * S_m) / sum of w_m      # default w_m = 1
overall  = 0.35 * asset_quality + 0.40 * profit + 0.25 * efficiency
```

Two properties that must be printed on every chart that shows a score:

1. Scores are computed **within** each year across the three banks, so the scores in a
   given year always span 0 to 100. **100 means "best of the three that year"**, not
   "good in absolute terms".
2. Every metric always produces both a 0 and a 100, because with three banks min-max is
   forced to the ends. Small real differences therefore look large. Mitigation: **never
   show a score without the raw value next to it**, and check whether the ranking survives
   a rank-based and a z-score version of the same scorecard.

The brief's base weights (35/40/25) are the author's judgement, not a fact. That is
precisely what the sensitivity test measures, and the memo says so.

---

## 6. Sensitivity test design (the project's unique angle, strengthened)

The brief specifies 10,000 random weight draws with seed 42. That is kept, and wrapped in
four extra tests so the conclusion cannot be an artefact of one arbitrary choice:

1. **Random weights.** Draw 10,000 weight sets from Dirichlet(1,1,1) - the uniform
   distribution over the weight triangle, so no weighting is privileged - seed 42.
   Report P(bank ranks #1), P(#2), P(#3).
2. **Exact flip threshold.** Because there are only three pillars, the winner is a
   function on a triangle and the flip boundaries are straight lines. Sweep a fine grid
   over the triangle and report, for each bank, the **smallest change in each weight that
   flips the winner**. This is a far more useful sentence than a single percentage.
3. **Method sensitivity.** Repeat (1) under the all-years pool, under z-scores and under
   ranks instead of min-max. If the ranking changes with the method, that is the finding.
4. **Data sensitivity.** Leave-one-metric-out, and perturb each input by a plausible
   measurement tolerance, to show how much of the result rests on a single reported number.
5. **Regime sensitivity.** (1) on FY2022-FY2026 and again on FY2024-FY2026, so the merger
   is not doing the work.

Output: a table plus one chart - "who wins how often" - and the flip thresholds.

---

## 7. Pipeline contract (P3)

**`data/source_log.csv` - one row per number, and no number may enter the pipeline
without one.**

```
source_id, bank, basis, period_type, period_label, metric_code, metric_name,
value_as_reported, unit_as_reported, value_normalised, unit_normalised,
document_title, document_type, document_date, page_number, table_reference,
url, downloaded_on, sha256_of_document, verified_by, verification_method,
definition_variant, status, notes
```

`status` is one of: `verified`, `two_source_confirmed`, `conflict`, `UNVERIFIED`.
A `conflict` row carries both values and an explanation. `UNVERIFIED` is a legitimate,
expected value - a blank is better than a guess.

**`data/processed/master_long.csv`** - the analysis input:
`bank, period, period_type, metric_code, value, unit, basis, source_id,
definition_variant, score_eligible`.

**`run_all.py`**

```bash
python run_all.py                  # rebuild everything from data/processed
python run_all.py --verify-raw     # also re-hash data/raw against the source log
python run_all.py --fetch          # re-download what the source log marks fetchable
python run_all.py --check-determinism   # run twice, compare output hashes
```

Every run writes `outputs/manifest.json`: input hashes, output hashes, row counts,
library versions, and the result of every sanity check.

**Tests (`tests/`)** must include: schema and range checks; the P&L ladder identity; Net
NPA <= Gross NPA; ROA recomputed from profit and average assets within 0.05 percentage
points of reported; no scored metric carrying a currency unit; every scored value having a
source row with a non-`UNVERIFIED` status; and the determinism test.

---

## 8. Risk register - what will probably end up UNVERIFIED

Named now so that finding them later is expected, not a surprise:

1. **Slippage ratio** and **credit cost** for several bank-years: not disclosed by every
   bank in every year, and defined in more than one way.
2. **Provision coverage ratio** conventions (technical write-offs in or out).
3. **HDFC's "core" cost-to-income** against the plain version used elsewhere.
4. **RBI system-level FY2026 data**, if the relevant publication has not appeared yet.
5. **Q1 FY2027 for all three banks** if any bank's document is not reachable - and RBI PDF
   downloads are already known to be blocked from this machine.
6. **Pre-merger HDFC comparatives**, where a restated figure replaced the original.

---

## 9. Phases, definition of done, and effort

| Phase | Definition of done | Realistic effort |
|---|---|---|
| P0 | This document | done |
| P1 | Folder structure, `environment.yml`, `.gitignore`, `git init`, README | **done** |
| P2 | Source log schema built; documents collected; every FY22-FY26 metric for 3 banks entered or marked UNVERIFIED; each number has a source row | 8-15 hours, the largest phase |
| P3 | `run_all.py` rebuilds every table and chart from `data/processed`; all tests pass; determinism proven | 3-5 hours |
| P4 | Tableau workbook built against Tableau **Public**, with method and sources tab | 2-3 hours |
| P5 | `case_study_memo.pdf` and `understanding_guide.pdf` generate from the pipeline | 3-5 hours |
| P6 | Repo published, raw documents excluded, licence and citation added, tag v1.0, final audit | 1-2 hours |

Total: roughly 18-30 hours of work, spread over 2-4 weeks. The data collection phase
dominates, and it cannot be compressed by writing better code - only by accepting more
UNVERIFIED cells or by reducing the metric set.

---

## 10. What the original brief gets right (keep these)

1. **The standalone-only rule** removes the single most common source of silently wrong
   bank comparisons.
2. **The merger flag** shows the author already distrusts long-run comparability.
3. **Fixed seed, pinned versions and hash logs** - reproducibility from the start rather
   than bolted on.
4. **The two-source rule** is the correct instinct even where it needs refining.
5. **The sensitivity test** is the genuine intellectual contribution here. Most student
   bank comparisons assert a ranking; this one measures how much the ranking depends on
   the author's choices.
6. **No buy/sell advice**, and facts separated from judgement.

---

## 11. Decisions taken (confirmed by the project owner, 2026-10-10)

1. **Project location** - `~/Documents/bank-scorecard`. Built and confirmed.
2. **Tableau target** - **Tableau Public**, the product actually installed on this Mac.
   The P4 build guide is written against Tableau Public's feature set. Its exact workbook
   limits (extract handling, saving) are verified in P4 rather than assumed now.
3. **Scorecard window** - **FY2022-FY2026 is the primary scorecard**, with
   **FY2024-FY2026 (merger-clean) reported as a robustness panel**. Both are always shown.
   The verdict is only described as "stable" if it survives the shorter window too.
4. **Data collection split** - the machine fetches everything it can (ICICI Bank works end
   to end); the owner downloads only what is blocked (HDFC Bank, State Bank of India and
   RBI), following `data/raw/MANUAL_DOWNLOAD_NEEDED.txt`.
5. **Project environment** - created now from `environment.yml`.

Open decisions remaining: none.
