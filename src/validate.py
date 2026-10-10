"""validate.py - the automatic sanity checks.

Two levels, deliberately separate:

  FAIL - the value is impossible or the series is incomplete. The pipeline stops,
         because any number computed from it would be wrong.
  WARN - the value is possible but worth a human look (a bank that includes
         technical write-offs can legitimately report a provision coverage ratio
         above 100%, so that is a warning, not an error).
  SKIP - the check could not run because its prerequisite numbers are not in the
         source log yet. A skip is reported, never silently ignored.

The list of FAIL vs WARN matters: an over-strict pipeline gets its checks weakened
to make it run. Everything here is either genuinely impossible or genuinely absent.
"""
from __future__ import annotations
import pandas as pd
from src.config import BANKS, METRICS, WINDOW_PRIMARY

FAIL, WARN, SKIP, PASS = "FAIL", "WARN", "SKIP", "PASS"


def _val(df, bank, code, period, basis="standalone"):
    s = df[(df.bank == bank) & (df.metric_code == code)
           & (df.period_label == period) & (df.basis == basis)]
    s = s[s.has_value]
    return None if s.empty else float(s.value_normalised.iloc[0])


def check_schema(df):
    bad = sorted(set(df["status"]) - {"verified", "two_source_confirmed", "conflict", "UNVERIFIED",
                                     "auto_extracted", "ocr_extracted", "manually_corrected",
                                     "MANUAL_REQUIRED"})
    if bad:
        return FAIL, "status", f"invalid status value(s): {bad}"
    bad = sorted(set(df["verification_method"]) - {"recomputed", "cross_issuer", "same_issuer_2_docs",
                                                     "single_source", "automated_regex",
                                                     "coordinate_text", "human_verified", ""})
    if bad:
        return FAIL, "verification_method", f"invalid verification_method(s): {bad}"
    unknown = sorted(set(df["metric_code"]) - set(METRICS))
    if unknown:
        return FAIL, "metric_code", f"metric(s) not in the registry: {unknown}"
    return PASS, "schema", "all status/verification/metric values are known"


def check_no_missing_years(df, window=None):
    """Any metric that has started must cover every year of the window.

    A year counts as covered if a row EXISTS for it, even when the row has no
    value and status UNVERIFIED. That is the honest way to say "we looked and
    could not verify it". A year with no row at all means nobody looked.
    """
    window = window or WINDOW_PRIMARY
    problems = []
    annual = df[df.is_annual]
    for (bank, code), sub in annual.groupby(["bank", "metric_code"]):
        have = set(sub["period_label"])
        missing = [y for y in window if y not in have]
        if missing and have:
            problems.append(f"{bank}/{code}: no row for {','.join(missing)}")
    if problems:
        return FAIL, "no_missing_years", "; ".join(problems[:8]) + (
            f" (+{len(problems)-8} more)" if len(problems) > 8 else "")
    return PASS, "no_missing_years", f"every started metric covers {window[0]}-{window[-1]}"


def check_net_npa_le_gross_npa(df):
    bad = []
    for bank in df["bank"].unique():
        for period in df["period_label"].unique():
            net = _val(df, bank, "net_npa_pct", period)
            gross = _val(df, bank, "gross_npa_pct", period)
            if net is not None and gross is not None and net > gross + 1e-9:
                bad.append(f"{bank} {period}: Net NPA {net}% > Gross NPA {gross}%")
    if bad:
        return FAIL, "net_npa_le_gross_npa", "; ".join(bad)
    return PASS, "net_npa_le_gross_npa", "Net NPA never exceeds Gross NPA"


def check_impossible_values(df):
    """Hard fail only on things that cannot exist. Growth rates may be negative."""
    bad = []
    for _, r in df[df.has_value].iterrows():
        v = float(r.value_normalised)
        if r.metric_code in {"gross_npa_pct", "net_npa_pct", "nim_pct"} and v < 0:
            bad.append(f"{r.bank} {r.period_label} {r.metric_code}={v} (cannot be negative)")
        if r.metric_code == "pcr_pct" and v < 0:
            bad.append(f"{r.bank} {r.period_label} pcr_pct={v} (cannot be negative)")
    if bad:
        return FAIL, "impossible_values", "; ".join(bad[:8])
    return PASS, "impossible_values", "no impossible level values"


def check_plausible_values(df):
    """Soft checks: possible, but a human should see them."""
    notes = []
    for _, r in df[df.has_value].iterrows():
        v = float(r.value_normalised)
        if r.metric_code == "pcr_pct" and v > 100:
            notes.append(f"{r.bank} {r.period_label} PCR={v}% >100% "
                         "(check whether technical write-offs are included)")
        if r.metric_code == "roa_pct" and not (-1.0 <= v <= 3.0):
            notes.append(f"{r.bank} {r.period_label} ROA={v}% is outside the usual range")
        if r.metric_code.endswith("_growth_pct") and v < 0:
            notes.append(f"{r.bank} {r.period_label} {r.metric_code}={v}% (negative growth is legitimate)")
    if notes:
        return WARN, "plausible_values", "; ".join(notes[:8]) + (
            f" (+{len(notes)-8} more)" if len(notes) > 8 else "")
    return PASS, "plausible_values", "no values need a second look"


def check_roa_recompute(df, tol=0.05):
    """ROA recomputed from profit and average assets must match the reported ROA.

    Average assets = mean of this year's and last year's total assets, which is
    the usual basis. This needs the rupee building blocks, so it skips cleanly
    when they are not in the source log yet.
    """
    checked, bad, skipped = 0, [], 0
    for bank in df["bank"].unique():
        for period in [p for p in df["period_label"].unique() if p.startswith("FY")]:
            rep = _val(df, bank, "roa_pct", period)
            pat = _val(df, bank, "net_profit_inr", period)
            ta_now = _val(df, bank, "total_assets_inr", period)
            prev = f"FY{int(period[2:]) - 1}"
            ta_prev = _val(df, bank, "total_assets_inr", prev)
            if None in (rep, pat, ta_now, ta_prev):
                skipped += 1
                continue
            avg_assets = (ta_now + ta_prev) / 2.0
            if avg_assets == 0:
                skipped += 1
                continue
            calc = pat / avg_assets * 100.0
            checked += 1
            if abs(calc - rep) > tol:
                bad.append(f"{bank} {period}: reported ROA {rep:.2f}% vs recomputed "
                           f"{calc:.2f}% (diff {calc-rep:+.2f}pp > {tol}pp)")
    if checked == 0:
        return SKIP, "roa_recompute", (
            "needs roa_pct + net_profit_inr + total_assets_inr for two consecutive "
            "years; not enough in the source log yet")
    if bad:
        return FAIL, "roa_recompute", f"{len(bad)} mismatch(es): " + "; ".join(bad[:5])
    return PASS, "roa_recompute", f"{checked} bank-year(s) within {tol}pp ({skipped} skipped)"


def check_pl_ladder(df, abs_tol_cr=25.0, rel_tol=0.005):
    """Net profit must equal the P&L ladder from interest and other income down."""
    checked, bad, skipped = 0, [], 0
    for bank in df["bank"].unique():
        for period in [p for p in df["period_label"].unique() if p.startswith("FY")]:
            nii = _val(df, bank, "nii_inr", period)
            oth = _val(df, bank, "other_income_inr", period)
            ope = _val(df, bank, "opex_inr", period)
            pro = _val(df, bank, "provisions_inr", period)
            tax = _val(df, bank, "tax_inr", period)
            pat = _val(df, bank, "net_profit_inr", period)
            if None in (nii, oth, ope, pro, pat):
                skipped += 1
                continue
            calc = nii + oth - ope - pro - (tax or 0.0)
            tol = max(abs_tol_cr, abs(pat) * rel_tol)
            checked += 1
            if abs(calc - pat) > tol:
                bad.append(f"{bank} {period}: ladder gives {calc:,.0f} vs reported "
                           f"{pat:,.0f} crore (diff {calc-pat:+,.0f}, tol {tol:,.0f})")
    if checked == 0:
        return SKIP, "pl_ladder", (
            "needs NII + other income + operating expenses + provisions + net profit; "
            "not enough in the source log yet")
    if bad:
        return FAIL, "pl_ladder", f"{len(bad)} mismatch(es): " + "; ".join(bad[:5])
    return PASS, "pl_ladder", f"{checked} bank-year(s) tie out ({skipped} skipped)"


def check_units(df):
    """Scored metrics must be percentages. Currency must never be score-eligible."""
    bad = []
    scored = df[df.score_eligible]
    wrong = scored[scored.unit_normalised != "pct"]
    if not wrong.empty:
        bad.append(f"score-eligible rows with non-pct unit: "
                   f"{sorted(set(wrong.metric_code))}")
    # A scored metric reported in different raw units across banks is a data-entry smell.
    mixed = (df[df.is_scored_metric & df.has_value]
             .groupby("metric_code")["unit_as_reported"].nunique())
    mixed = mixed[mixed > 1]
    if not mixed.empty:
        bad.append(f"scored metrics reported in mixed raw units (check entry): "
                   f"{sorted(mixed.index)}")
    if bad:
        return FAIL, "units", "; ".join(bad)
    return PASS, "units", "all scored metrics are percentages in one raw unit"


CHECKS = [
    ("schema", check_schema, ()),
    ("no_missing_years", check_no_missing_years, ()),
    ("net_npa_le_gross_npa", check_net_npa_le_gross_npa, ()),
    ("impossible_values", check_impossible_values, ()),
    ("plausible_values", check_plausible_values, ()),
    ("roa_recompute", check_roa_recompute, ()),
    ("pl_ladder", check_pl_ladder, ()),
    ("units", check_units, ()),
]


def run_all_checks(df) -> pd.DataFrame:
    rows = []
    for name, fn, _ in CHECKS:
        try:
            status, check, detail = fn(df)
        except Exception as exc:                      # a broken check is a bug, report it
            status, check, detail = FAIL, name, f"check raised {type(exc).__name__}: {exc}"
        rows.append(dict(status=status, check=check, detail=detail))
    return pd.DataFrame(rows)


def hard_failures(report: pd.DataFrame) -> pd.DataFrame:
    return report[report.status == FAIL]
