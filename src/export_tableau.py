"""export_tableau.py - clean long-format CSVs for Tableau Public.

Tableau cannot be scripted from here, so the pipeline's job is to hand Tableau
data that is already tidy: one row per (bank, period, metric) with no merged
header cells and no percentage signs inside numbers. A .hyper extract is only
attempted if tableauhyperapi is importable; CSV is the guaranteed path.
"""
from __future__ import annotations
import pandas as pd
from src.config import OUT_TABLEAU, PILLAR_WEIGHTS, METRICS


def export(df, scored=None, metric_scores=None, shares=None):
    OUT_TABLEAU.mkdir(parents=True, exist_ok=True)
    written = []

    d = df[df.has_value].copy()
    d["pillar"] = d["metric_code"].map(lambda m: METRICS.get(m, {}).get("pillar") or "context")
    d["metric_name"] = d["metric_code"].map(lambda m: METRICS.get(m, {}).get("name", m))
    fact = d[["bank", "basis", "period_type", "period_label", "metric_code",
              "metric_name", "pillar", "value_normalised", "unit_normalised",
              "status", "verification_method", "source_id"]]
    p = OUT_TABLEAU / "fact_metrics.csv"
    fact.to_csv(p, index=False)
    written.append((p, len(fact)))

    pd.DataFrame([
        dict(pillar=k, base_weight=v) for k, v in PILLAR_WEIGHTS.items()
    ]).to_csv(OUT_TABLEAU / "dim_pillar_weights.csv", index=False)
    written.append((OUT_TABLEAU / "dim_pillar_weights.csv", len(PILLAR_WEIGHTS)))

    if metric_scores is not None and not metric_scores.empty:
        p = OUT_TABLEAU / "fact_scores.csv"
        metric_scores.to_csv(p, index=False)
        written.append((p, len(metric_scores)))
    if scored is not None and not scored.empty:
        p = OUT_TABLEAU / "fact_overall_scores.csv"
        scored.to_csv(p, index=False)
        written.append((p, len(scored)))
    if shares is not None and not shares.empty:
        p = OUT_TABLEAU / "sens_win_shares.csv"
        shares.to_csv(p, index=False)
        written.append((p, len(shares)))

    try:
        from tableauhyperapi import HyperProcess, Connection, Telemetry   # noqa: F401
        hyper_available = True
    except Exception:
        hyper_available = False
    return written, hyper_available
