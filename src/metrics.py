"""metrics.py - trends, year-on-year change, growth rates and profit quality.

Three things live here:
  1. trend_table / pivot_metric - the raw series, bank by bank and year by year.
  2. cagr                      - growth over time, which refuses to cross the
                                 HDFC merger because the number would be an
                                 artefact of the merger, not of the business.
  3. profit_quality            - the decomposition of profit growth into the part
                                 the bank earned and the part that came from
                                 provisioning less. Same idea as the DuPont step
                                 (src/dupont.py), applied to the P&L instead of
                                 the balance sheet.

Deliberate omission: no CAGR is computed across the HDFC merger. FY2024 is a
transition year, so a multi-year growth rate spanning it would be an artefact of
the merger, not of the business. `cagr` refuses to cross the break unless the
caller explicitly overrides it.
"""
from __future__ import annotations
import pandas as pd
from src.config import METRICS, WINDOW_PRIMARY, HDFC_MERGER_DATE

# HDFC Bank absorbed HDFC Ltd effective 1 July 2023, which falls inside FY2024.
# So for HDFC FY2024 is a stub year (about nine months of combined operations),
# and any year-on-year change whose base or end sits in FY2024 is partly a
# measurement artefact. Those rows are flagged, never silently dropped.
HDFC_TRANSITION_YEAR = "FY2024"
MERGER_AFFECTED_BANK = "HDFC"

QUALITY_COLUMNS = [
    "bank", "period_label", "base_period", "operating_profit_inr",
    "operating_profit_base_inr", "d_operating_profit_inr", "d_provisions_inr",
    "d_tax_inr", "d_pat_inr", "pat_from_operations_inr", "pat_from_provisions_inr",
    "pat_from_tax_inr", "identity_residual_inr", "share_from_operations_pct",
    "share_from_provisions_pct", "share_from_tax_pct", "quality_verdict",
    "merger_affected", "note",
]


def trend_table(df, window=None) -> pd.DataFrame:
    """Raw values per bank, period and metric, with the YoY change alongside."""
    window = window or WINDOW_PRIMARY
    d = df[df.is_annual & df.period_label.isin(window) & df.has_value].copy()
    d = d.sort_values(["bank", "metric_code", "period_label"])
    d["yoy_change_pp"] = d.groupby(["bank", "metric_code"])["value_normalised"].diff()
    d["yoy_pct"] = (d.groupby(["bank", "metric_code"])["value_normalised"]
                    .pct_change() * 100.0)
    d["metric_name"] = d["metric_code"].map(lambda m: METRICS.get(m, {}).get("name", m))
    d["pillar"] = d["metric_code"].map(lambda m: METRICS.get(m, {}).get("pillar") or "context")
    return d[["bank", "period_label", "metric_code", "metric_name", "pillar",
              "value_normalised", "unit_normalised", "yoy_change_pp", "yoy_pct",
              "status", "source_id"]]


def pivot_metric(df, metric_code, window=None) -> pd.DataFrame:
    """Bank x year matrix of one metric - the shape you actually want to read."""
    window = window or WINDOW_PRIMARY
    d = df[df.is_annual & (df.metric_code == metric_code)
           & df.period_label.isin(window) & df.has_value]
    if d.empty:
        return pd.DataFrame(index=[], columns=[])
    return d.pivot_table(index="bank", columns="period_label",
                         values="value_normalised", aggfunc="first").reindex(columns=window)


def _getter(annual: pd.DataFrame, bank: str):
    """Return get(metric_code, period_label) -> float | None, read from one frame."""
    sub = annual[annual.bank == bank]

    def get(code, period):
        s = sub[(sub.metric_code == code) & (sub.period_label == period)]
        return None if s.empty else float(s.value_normalised.iloc[0])
    return get


def profit_quality(df, window=None) -> pd.DataFrame:
    """Where did the profit growth come from: better operations, or fewer provisions?

    The identity being decomposed is the same P&L ladder that
    `validate.check_pl_ladder` tests:

        operating profit  = net interest income + other income - operating expenses
        profit before tax = operating profit - provisions and contingencies
        net profit        = profit before tax - tax expense

    so, exactly, year on year:

        d(net profit) = d(operating profit) - d(provisions) - d(tax)

    A rupee of extra profit that arrives because provisions fell is a different
    kind of rupee from one the bank actually earned before provisions: the first
    may reverse, the second repeats. This table separates the two and keeps the
    residual of the identity, so the separation can be audited rather than
    trusted.

    Columns per bank-year:
        d_operating_profit_inr   year-on-year change in operating profit
        d_provisions_inr         year-on-year change in provisions
        d_tax_inr                year-on-year change in tax expense
        d_pat_inr                year-on-year change in net profit
        pat_from_operations_inr  the d(operating profit) contribution
        pat_from_provisions_inr  the -d(provisions) contribution
        pat_from_tax_inr         the -d(tax) contribution
        identity_residual_inr    the three contributions minus actual d(PAT)
        share_from_operations_pct / share_from_provisions_pct / share_from_tax_pct
        quality_verdict          operations-led / provision-led / mixed / no growth

    Rules: a missing input yields an empty cell, never an estimate. Shares are
    left empty when net profit did not grow, because a share of a fall is not a
    meaningful sentence.
    """
    window = window or WINDOW_PRIMARY
    annual = df[df.is_annual & df.has_value]
    if annual.empty:
        return pd.DataFrame(columns=QUALITY_COLUMNS)

    rows = []
    for bank in sorted(annual["bank"].unique()):
        get = _getter(annual, bank)
        for period in [p for p in sorted(annual[annual.bank == bank]["period_label"].unique())
                       if p in window]:
            prev = f"FY{int(period[2:]) - 1}"

            def op(yr):
                nii, oth, ope = (get("nii_inr", yr), get("other_income_inr", yr),
                                 get("opex_inr", yr))
                return None if None in (nii, oth, ope) else nii + oth - ope

            def delta(code):
                a, b = get(code, period), get(code, prev)
                return None if None in (a, b) else a - b

            d_prov, d_tax = delta("provisions_inr"), delta("tax_inr")
            d_op = None if None in (op(period), op(prev)) else op(period) - op(prev)
            d_pat = delta("net_profit_inr")

            from_op = d_op
            from_prov = None if d_prov is None else -d_prov
            from_tax = None if d_tax is None else -d_tax
            residual = (None if None in (from_op, from_prov, from_tax, d_pat)
                        else from_op + from_prov + from_tax - d_pat)

            # Shares only make sense when profit actually grew.
            growing = d_pat is not None and d_pat > 0
            shares = {}
            for label, part in (("operations", from_op), ("provisions", from_prov),
                                ("tax", from_tax)):
                shares[label] = (round(part / d_pat * 100.0, 1)
                                 if (growing and part is not None) else None)

            missing = [n for n, v in (("operating profit", d_op), ("provisions", d_prov),
                                      ("tax", d_tax), ("net profit", d_pat)) if v is None]
            if missing:
                verdict = ""
                note = (f"cannot decompose {prev}->{period}: missing {', '.join(missing)}"
                        f" (or its {prev} comparatives)")
            elif not growing:
                verdict = "no profit growth to decompose"
                note = f"net profit changed by {d_pat:,.0f} crore, not a rise"
            elif shares["provisions"] is not None and shares["provisions"] >= 60:
                verdict = "provision-led"
                note = "most of the rise came from provisioning less, not earning more"
            elif shares["operations"] is not None and shares["operations"] >= 60:
                verdict = "operations-led"
                note = "most of the rise came from operating profit before provisions"
            else:
                verdict = "mixed"
                note = "no single driver explains most of the rise"

            merger = (bank == MERGER_AFFECTED_BANK
                      and HDFC_TRANSITION_YEAR in (period, prev))
            if merger:
                note += (f"; {HDFC_TRANSITION_YEAR} is the merger transition year for"
                         f" {MERGER_AFFECTED_BANK} ({HDFC_MERGER_DATE}), so this change"
                         " reflects the merger as much as the business")

            rows.append(dict(
                bank=bank, period_label=period, base_period=prev,
                operating_profit_inr=op(period), operating_profit_base_inr=op(prev),
                d_operating_profit_inr=d_op, d_provisions_inr=d_prov, d_tax_inr=d_tax,
                d_pat_inr=d_pat, pat_from_operations_inr=from_op,
                pat_from_provisions_inr=from_prov, pat_from_tax_inr=from_tax,
                identity_residual_inr=residual,
                share_from_operations_pct=shares["operations"],
                share_from_provisions_pct=shares["provisions"],
                share_from_tax_pct=shares["tax"],
                quality_verdict=verdict, merger_affected=merger, note=note,
            ))
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)


def cagr(df, metric_code, start, end, allow_merger_crossing=False):
    """Compound annual growth rate between two years, per bank.

    Refuses to cross the July 2023 merger unless explicitly allowed, because the
    resulting number would compare a merged bank with an unmerged one.
    """
    crosses = int(start[2:]) <= 2023 <= int(end[2:])
    if crosses and not allow_merger_crossing:
        raise ValueError(
            f"Refusing to compute CAGR {start}->{end}: it crosses the HDFC merger "
            f"({HDFC_MERGER_DATE}). Pass allow_merger_crossing=True to override, "
            f"and label the result as merger-affected.")
    years = int(end[2:]) - int(start[2:])
    out = {}
    for bank in sorted(df["bank"].unique()):
        a = df[(df.bank == bank) & (df.metric_code == metric_code)
               & (df.period_label == start) & df.has_value]
        b = df[(df.bank == bank) & (df.metric_code == metric_code)
               & (df.period_label == end) & df.has_value]
        if a.empty or b.empty:
            out[bank] = None
            continue
        v0, v1 = float(a.value_normalised.iloc[0]), float(b.value_normalised.iloc[0])
        out[bank] = None if (v0 <= 0 or years <= 0) else ((v1 / v0) ** (1 / years) - 1) * 100
    return out
