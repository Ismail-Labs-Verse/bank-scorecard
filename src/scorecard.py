"""scorecard.py - converts raw metrics into 0-100 scores.

THE FORMULA, EXACTLY (this is the one the memo must quote):

    For metric m, financial year y, over the three banks b:
        d_m  = +1 if higher is better, -1 if lower is better
        t(b) = d_m * x(b)                       # orient so higher = better
        S_m(b) = 100 * (t(b) - min t) / (max t - min t)
        if max t == min t: S_m(b) = 50 for all three (flagged "degenerate")

        pillar  = mean of the S_m of the metrics in that pillar
        overall = sum(w_p * pillar_p) / sum(w_p over pillars that exist)

    Base weights: asset quality 0.35, profit 0.40, efficiency 0.25.

TWO PROPERTIES THAT MUST BE PRINTED ON EVERY CHART SHOWING A SCORE:
  1. Scores are computed WITHIN each year across the three banks, so in any given
     year the three banks span 0 to 100. 100 means "best of the three that year",
     NOT "good in absolute terms".
  2. Every metric always produces both a 0 and a 100. Small real differences
     therefore look large. That is why no score is ever shown without its raw value.
"""
from __future__ import annotations
import pandas as pd
from src.config import PILLAR_WEIGHTS, WINDOW_PRIMARY, METRICS

PILLARS = ["asset_quality", "profit", "efficiency"]


def _minmax(series: pd.Series, direction: int):
    t = series.astype(float) * direction
    lo, hi = t.min(), t.max()
    if hi == lo:
        return pd.Series(50.0, index=series.index), True
    return 100.0 * (t - lo) / (hi - lo), False


def metric_scores(df, window=None):
    """One row per bank-year-metric: the raw value, the direction, and the score."""
    window = window or WINDOW_PRIMARY
    d = df[df.score_eligible & df.period_label.isin(window)]
    rows, skipped = [], []
    for (period, code), sub in d.groupby(["period_label", "metric_code"]):
        sub = sub.drop_duplicates(subset="bank")
        if len(sub) < 2:
            skipped.append(f"{period}/{code}: only {len(sub)} bank(s) with a value")
            continue
        direction = METRICS[code]["direction"]
        scores, degenerate = _minmax(sub.set_index("bank")["value_normalised"], direction)
        for _, r in sub.iterrows():
            rows.append(dict(
                bank=r["bank"], period_label=period, metric_code=code,
                metric_name=METRICS[code]["name"], pillar=METRICS[code]["pillar"],
                raw_value=float(r["value_normalised"]), direction=direction,
                score=float(scores[r["bank"]]), degenerate=degenerate,
            ))
    return pd.DataFrame(rows), skipped


def pillar_scores(ms: pd.DataFrame) -> pd.DataFrame:
    """Bridge from metric scores to pillar scores. Weight-independent."""
    if ms.empty:
        return pd.DataFrame(columns=["bank", "period_label"] + PILLARS)
    out = (ms.groupby(["bank", "period_label", "pillar"])["score"].mean()
             .unstack("pillar"))
    for p in PILLARS:
        if p not in out.columns:
            out[p] = float("nan")
    return out[PILLARS].reset_index()


def overall_scores(ps: pd.DataFrame, weights=None) -> pd.DataFrame:
    """Apply the pillar weights, on a basis that is the same for every bank.

    THE MISSING-PILLAR PROBLEM
    --------------------------
    Dividing each bank's weighted total by the weights it personally has data
    for is the obvious approach and it is wrong: a bank measured on two pillars
    would be scored against a bank measured on three, and would not be
    penalised for the gap. Two banks are only comparable if the same pillars
    are used for both.

    So a pillar is used for a given year only when **every** bank has a value
    for it in that year. The remaining weights are then renormalised
    proportionally over the pillars that survive. This study has no efficiency
    data for any bank, so that pillar is dropped for every year and the 35/40/25
    weights become a 35/40 pair scaled to sum to one - evenly applied, and
    visible in the ``pillars_used`` and ``data_limitation`` columns.

    Returns the pillar table with ``overall``, ``pillars_used`` and
    ``data_limitation`` added.
    """
    weights = weights or PILLAR_WEIGHTS
    if ps.empty:
        out = ps.copy()
        out["overall"] = pd.Series(dtype=float)
        out["pillars_used"] = pd.Series(dtype="Int64")
        out["data_limitation"] = pd.Series(dtype=str)
        return out

    out = ps.copy()
    present = [p for p in PILLARS if p in out.columns]

    # Which pillars are complete for all banks, year by year.
    usable_by_year: dict[str, list[str]] = {}
    for period, group in out.groupby("period_label"):
        usable_by_year[period] = [p for p in present if group[p].notna().all()]

    totals: list[float] = []
    counts: list[int] = []
    for _, row in out.iterrows():
        pillars = usable_by_year.get(row["period_label"], [])
        if not pillars:
            totals.append(float("nan"))
            counts.append(0)
            continue
        numerator = sum(weights[p] * float(row[p]) for p in pillars)
        denominator = sum(weights[p] for p in pillars)
        totals.append(numerator / denominator)
        counts.append(len(pillars))

    out["overall"] = totals
    out["pillars_used"] = pd.array(counts, dtype="Int64")

    full_set = len(present)
    out["data_limitation"] = [
        ("" if n == full_set else
         f"{full_set - n} of {full_set} pillars have no value for every bank; "
         f"weights renormalised over the {n} pillar(s) available: "
         f"{', '.join(usable_by_year.get(p, []))}")
        for p, n in zip(out["period_label"], counts)
    ]
    return out


def rank_table(scored: pd.DataFrame) -> pd.DataFrame:
    """Rank within each year, then the mean overall score per bank."""
    if scored.empty:
        return scored
    out = scored.copy()
    out["rank_in_year"] = (out.groupby("period_label")["overall"]
                              .rank(ascending=False, method="min").astype("Int64"))
    return out.sort_values(["period_label", "rank_in_year"])


def mean_by_bank(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame(columns=["bank", "mean_overall"] + PILLARS)
    g = scored.groupby("bank")
    out = g[["overall"]].mean().rename(columns={"overall": "mean_overall"})
    for p in PILLARS:
        if p in scored.columns:
            out[p] = g[p].mean()
    if "pillars_used" in scored.columns:
        out["mean_pillars_used"] = g["pillars_used"].mean()
    return out.sort_values("mean_overall", ascending=False).reset_index()


def winner(scored: pd.DataFrame):
    m = mean_by_bank(scored)
    return None if m.empty else str(m.iloc[0]["bank"])


def build(df, window=None, weights=None):
    """Convenience: raw master table -> metric scores -> pillars -> overall."""
    ms, skipped = metric_scores(df, window)
    ps = pillar_scores(ms)
    sc = rank_table(overall_scores(ps, weights))
    return dict(metric_scores=ms, pillar_scores=ps, scored=sc,
                summary=mean_by_bank(sc), skipped=skipped,
                window=window or WINDOW_PRIMARY)
