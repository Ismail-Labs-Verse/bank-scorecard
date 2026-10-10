"""sensitivity.py - the project's unique angle.

The brief asks for 10,000 random weight draws with seed 42. That is kept, and
wrapped in four extra tests so the conclusion cannot be an artefact of one
arbitrary choice. The key efficiency: pillar scores do NOT depend on the weights,
so they are computed once and every one of the 10,000 draws is then a weighted
sum. That is what makes 10,000 draws instant.

Tests:
  1. random_win_shares    - Dirichlet(1,1,1), uniform over the weight triangle
  2. flip_ranges          - exact weight range where the winner changes (1-D slices)
  3. simplex_grid         - full triangle map, step-controlled
  4. method_sensitivity   - min-max vs z-score vs rank
  5. metric_leave_one_out - does one metric carry the result?
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.config import PILLAR_WEIGHTS, SEED, N_SENSITIVITY_DRAWS, METRICS
from src.scorecard import PILLARS

RANKS = [1, 2, 3]


def _pillar_matrix(ps: pd.DataFrame):
    """Mean pillar score per bank -> DataFrame indexed by bank, columns = pillars."""
    if ps.empty:
        return pd.DataFrame(columns=PILLARS)
    return ps.groupby("bank")[PILLARS].mean()


def _winner_from_weights(m: pd.DataFrame, w: np.ndarray, banks):
    totals = m.loc[banks, PILLARS].fillna(0.0).values @ w
    return banks[int(np.argmax(totals))]


def random_win_shares(ps, n=N_SENSITIVITY_DRAWS, seed=SEED):
    """P(bank ranks #1) / P(#2) / P(#3) over n random weight vectors.

    Dirichlet(1,1,1) is the uniform distribution over the weight triangle, so no
    weighting is privileged. Seed is fixed so the result is reproducible.
    """
    m = _pillar_matrix(ps)
    if m.empty:
        return pd.DataFrame(columns=["bank"] + [f"p_rank{r}" for r in RANKS])
    banks = list(m.index)
    rng = np.random.default_rng(seed)
    W = rng.dirichlet(np.ones(len(PILLARS)), size=n)          # (n, 3)
    totals = m[PILLARS].fillna(0.0).values @ W.T              # (banks, n)
    order = np.argsort(-totals, axis=0)                        # best first
    rows = []
    for i, bank in enumerate(banks):
        rank_positions = np.argmax(order == i, axis=0) + 1     # 1,2,3
        rows.append({"bank": bank, **{f"p_rank{r}": float((rank_positions == r).mean())
                                     for r in RANKS},
                     "p_top1_pct": float((rank_positions == 1).mean() * 100)})
    return pd.DataFrame(rows).sort_values("p_rank1", ascending=False).reset_index(drop=True)


def flip_ranges(ps, step=0.005):
    """For each pillar, the contiguous weight range (around the base weights) over
    which the winner does not change, with the other weights held in proportion.

    This answers the useful question: "how far would I have to change this weight
    before the answer flips?"
    """
    m = _pillar_matrix(ps)
    if m.empty:
        return pd.DataFrame(columns=["pillar", "base_weight", "winner", "range_low",
                                     "range_high", "flips_at_low", "flips_at_high"])
    banks = list(m.index)
    base = dict(PILLAR_WEIGHTS)
    rows = []
    for pillar in PILLARS:
        others = [p for p in PILLARS if p != pillar]
        other_total = sum(base[p] for p in others) or 1.0
        grid = np.arange(0.0, 1.0 + step / 2, step)
        winners = []
        for wv in grid:
            w = {}
            w[pillar] = wv
            for p in others:
                w[p] = base[p] / other_total * (1.0 - wv)
            winners.append(_winner_from_weights(m, np.array([w[p] for p in PILLARS]), banks))
        winners = np.array(winners)
        base_w = base[pillar]
        base_idx = int(np.argmin(np.abs(grid - base_w)))
        base_winner = winners[base_idx]
        lo = base_idx
        while lo - 1 >= 0 and winners[lo - 1] == base_winner:
            lo -= 1
        hi = base_idx
        while hi + 1 < len(grid) and winners[hi + 1] == base_winner:
            hi += 1
        rows.append(dict(
            pillar=pillar, base_weight=base_w, winner=base_winner,
            range_low=float(grid[lo]), range_high=float(grid[hi]),
            flips_at_low=(None if lo == 0 else f"{base_winner} -> {winners[lo-1]}"),
            flips_at_high=(None if hi == len(grid) - 1 else f"{base_winner} -> {winners[hi+1]}"),
        ))
    return pd.DataFrame(rows)


def simplex_grid(ps, step=0.05):
    """Map the whole weight triangle: how often each bank wins in each cell."""
    m = _pillar_matrix(ps)
    if m.empty:
        return pd.DataFrame(columns=["w_asset_quality", "w_profit", "w_efficiency", "winner"])
    banks = list(m.index)
    rows = []
    n = int(round(1.0 / step))
    for i in range(n + 1):
        for j in range(n + 1 - i):
            w = np.array([i * step, j * step, 1.0 - (i + j) * step])
            rows.append(dict(w_asset_quality=round(w[0], 4), w_profit=round(w[1], 4),
                             w_efficiency=round(w[2], 4),
                             winner=_winner_from_weights(m, w, banks)))
    return pd.DataFrame(rows)


def _rescore(df, method: str):
    """Recompute metric scores with an alternative normalisation method."""
    from src.scorecard import metric_scores, pillar_scores
    ms, _ = metric_scores(df)
    if ms.empty or method == "minmax":
        return pillar_scores(ms)
    out = []
    for (period, code), sub in ms.groupby(["period_label", "metric_code"]):
        d = sub.set_index("bank")["raw_value"].astype(float) * int(sub["direction"].iloc[0])
        if method == "zscore":
            sd = d.std(ddof=0)
            s = pd.Series(50.0, index=d.index) if sd == 0 else 50.0 + 15.0 * (d - d.mean()) / sd
        elif method == "rank":
            s = d.rank(ascending=True).sub(1).div(max(len(d) - 1, 1)) * 100.0
        else:
            raise ValueError(f"unknown method {method}")
        for bank, val in s.items():
            out.append(dict(bank=bank, period_label=period, metric_code=code,
                            pillar=METRICS[code]["pillar"], score=float(val)))
    return pillar_scores(pd.DataFrame(out))


def method_sensitivity(df):
    """Does the ranking survive changing the scoring method?"""
    from src.scorecard import overall_scores, mean_by_bank
    rows = []
    for method in ["minmax", "zscore", "rank"]:
        ps = _rescore(df, method)
        summary = mean_by_bank(overall_scores(ps))
        if summary.empty:
            continue
        for _, r in summary.iterrows():
            rows.append(dict(method=method, bank=r["bank"],
                             mean_overall=float(r["mean_overall"]),
                             rank=int(summary.index.get_loc(r.name) + 1)))
    return pd.DataFrame(rows)


def metric_leave_one_out(df, window=None):
    """Drop one scored metric at a time: does a single number carry the verdict?"""
    from src.scorecard import build
    full = build(df, window)
    base_winner = None
    if not full["summary"].empty:
        base_winner = str(full["summary"].iloc[0]["bank"])
    rows = []
    codes = sorted({c for c in df[df.is_scored_metric]["metric_code"].unique()})
    for code in codes:
        sub = df[df.metric_code != code]
        res = build(sub, window)
        w = None if res["summary"].empty else str(res["summary"].iloc[0]["bank"])
        rows.append(dict(dropped_metric=code,
                         metric_name=METRICS.get(code, {}).get("name", code),
                         winner_without=w, changed=(w != base_winner)))
    return pd.DataFrame(rows), base_winner
