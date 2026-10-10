# Tableau Build Guide

How to connect the exported CSVs and build the scorecard workbook from scratch.

> **Before you start:** this machine has **Tableau Public**, not Tableau Desktop.
> Everything below works in Tableau Public except saving to a `.twbx` file —
> Public saves to its own gallery or as `.twb`. If you have Desktop, the same
> steps apply.

---

## 1. The data you are connecting

Run `python run_all.py` first. It writes five files to `outputs/tableau/`:

| File | Grain | What it holds |
|---|---|---|
| `fact_metrics.csv` | bank × period × metric | Every reported value with its unit and verification status |
| `fact_scores.csv` | bank × period × metric | The 0–100 score for each metric, with the raw value beside it |
| `fact_overall_scores.csv` | bank × period | The three pillar scores, the overall score and the within-year rank |
| `sens_win_shares.csv` | bank | Probability of ranking #1 / #2 / #3 across 10,000 weight draws |
| `dim_pillar_weights.csv` | pillar | The base pillar weights (35 / 40 / 25) |

---

## 2. Connect

1. Open Tableau → **Connect → Text file** → `outputs/tableau/fact_metrics.csv`.
2. Repeat for the other four files.
3. In the Data Source page, click **Data → Edit Relationships** and leave all
   files *unrelated*. They are separate sources joined in the view, not in the
   model — this keeps the grain honest.
4. For each source, right-click the connection → **Extract** is not needed at
   this size; the files are kilobytes.

**Type fixes before you build anything:**

- `period_label` is a **string** (`FY2022`). Right-click → *Change Data Type →
  String* (it may already be). Do **not** convert it to a date: the label is the
  fiscal year, and Tableau's date parsing will invent quarters that do not exist.
- `bank` → set to *String*. `value_as_reported` → *Number (decimal)* if you plan
  to plot raw values from this file.

---

## 3. Calculated fields

Create these in `fact_metrics` unless stated otherwise. Copy the formulas exactly.

**Colour per bank** — one fixed colour per bank, used everywhere, forever:

```
CASE [Bank]
  WHEN "SBI"   THEN "#1B2A4A"
  WHEN "HDFC"  THEN "#D4AF37"
  WHEN "ICICI" THEN "#6B7A8F"
END
```

**Ranking within a year** (from `fact_overall_scores`):

```
RANK_DENSE(SUM([Overall]), 'desc')
```

**Gap to the leader** (from `fact_overall_scores`):

```
[Overall] - { FIXED [Period Label] : MAX([Overall]) }
```

**Peer median for a metric** (from `fact_scores`) — lets any bank be compared
against the middle of the field rather than against the best:

```
{ FIXED [Period Label], [Metric Code] : MEDIAN([Score]) }
```

**Is this the merger-affected year?** The HDFC merger completed 1 July 2023 and
falls inside FY2024. Every time series must mark it:

```
IF [Period Label] = "FY2024" THEN "HDFC merger year" ELSE "Comparable" END
```

**Verification flag** — so a reader can see which values a human has checked:

```
CASE [Status]
  WHEN "verified"            THEN "Checked"
  WHEN "two_source_confirmed" THEN "Confirmed in 2+ documents"
  WHEN "manually_corrected"  THEN "Corrected by hand"
  WHEN "auto_extracted"      THEN "Machine-extracted, unchecked"
  WHEN "ocr_extracted"       THEN "Read from chart, unchecked"
  WHEN "MANUAL_REQUIRED"     THEN "Not sourced"
END
```

**Score with its raw value** — the project's rule is that a score is never shown
without the number behind it:

```
[Score] + " (" + STR(ROUND([Raw Value], 2)) + ")"
```

**Win share as a percentage** (from `sens_win_shares`):

```
[P Rank1] * 100
```

---

## 4. Three dashboards

### Dashboard 1 — Executive summary

| Sheet | Mark type | Details |
|---|---|---|
| Overall score trend | **Line** | Columns `Period Label`, Rows `Overall`, Colour `Bank`, Path `Bank`. One line per bank |
| Rank by year | **Text table** | `Bank` on Rows, `Period Label` on Columns, `RANK_DENSE` as text, `Colour per bank` on Colour |
| KPI tile | **Text** | Big number: latest overall score per bank. Use a separate sheet per bank, stacked in a horizontal container |
| Who wins how often | **Bar** | `Bank` on Rows, `Win share` on Columns, sorted descending |

Lay the KPI tiles across the top, the trend below them, and the rank table on
the right.

**Add the merger line** to the trend sheet: Analytics pane → **Reference Line**
→ per cell, value on `Period Label` → constant `FY2024` → line style *dotted*,
label *HDFC merger, 1 Jul 2023*.

### Dashboard 2 — Portfolio risk and pillars

| Sheet | Mark type | Details |
|---|---|---|
| Pillar scores | **Small multiples** | Columns `Period Label`, Rows `Pillar`, Colour `Bank`. Change the Rows pill to *Measure Values* to show asset quality, profit and efficiency side by side |
| Metric heatmap | **Square** | Rows `Metric Name`, Columns `Period Label`, Colour `Score`, Label `Score with its raw value` |
| Bank vs peer median | **Dumbbell** | Dual axis: `Score` and `Peer median` on the same Rows, both as circles, synchronised axes |
| Verification grid | **Square** | Rows `Bank` + `Metric Name`, Columns `Period Label`, Colour `Verification flag` |

The verification grid is not decoration — it tells the reader which numbers are
safe to quote.

### Dashboard 3 — Sensitivity and method

| Sheet | Mark type | Details |
|---|---|---|
| Win share | **Horizontal bar** | `Bank` on Rows, `Win share` on Columns, sorted; label each bar |
| Flip threshold | **Text table** | From `sensitivity_flip_ranges.csv`: pillar, base weight, range low/high, what it flips to |
| Simplex grid | **Heatmap** | `W asset quality` on Columns, `W profit` on Rows, `Winner` on Colour — the whole weight triangle in one picture |
| Method and sources | **Text** | Metric definitions, the base weights, the source documents, the limitations |

---

## 5. Formatting rules that make it look professional

- Set a **custom sequential palette** from the three brand colours: `#1B2A4A`,
  `#D4AF37`, `#6B7A8F`. Never use Tableau's default rainbow on a heatmap.
- **Never** let colour be the only signal — pair it with a label or a marker
  shape, so the workbook survives greyscale printing.
- Hide gridlines on bar charts; keep faint horizontal gridlines on line charts.
- Format numbers: scores to 0 decimals, ratios to 2, currency in ₹ crore with
  thousands separators.
- Put the metric definition and the source document in the **tooltip**, not the
  axis title.
- Add a **Data sources** text box to every dashboard footer.

## 6. Publishing

Publish each dashboard to Tableau Public, then set the workbook's default view
to the executive summary. Reference the published URL in the repository README
so a reader can reach the interactive version without opening any file.
