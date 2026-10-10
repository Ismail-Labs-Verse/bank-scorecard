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
    """Apply the pillar weights. This is the only part that depends on them."""
    weights = weights or PILLAR_WEIGHTS
    if ps.empty:
        return ps.assign(overall=[])
    out = ps.copy()
    present = [p for p in PILLARS if p in out.columns]
    num = sum(weights[p] * out[p].fillna(0.0) for p in present)
    den = sum(weights[p] * out[p].notna() for p in present)
    out["overall"] = num / den.replace(0, float("nan"))
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
