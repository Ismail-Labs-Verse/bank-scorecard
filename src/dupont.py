"""dupont.py - why does one bank earn a higher return on equity?

ROE = ROA x leverage, where leverage = average assets / average equity.
A bank can beat its peers on ROE either by being more profitable per rupee of
assets (ROA) or by carrying more assets per rupee of equity (leverage). Those are
different businesses, so this decomposition is the honest way to compare them.
"""
from __future__ import annotations


def dupont_by_bank(df, window=None):
    """Returns one row per bank-year with the three components and the check."""
    rows = []
    annual = df[df.is_annual & df.has_value]
    for bank in sorted(annual["bank"].unique()):
        for period in sorted(annual[annual.bank == bank]["period_label"].unique()):
            def v(code):
                s = annual[(annual.bank == bank) & (annual.metric_code == code)
                           & (annual.period_label == period)]
                return None if s.empty else float(s.value_normalised.iloc[0])
            roe, roa = v("roe_pct"), v("roa_pct")
            assets, profit = v("total_assets_inr"), v("net_profit_inr")
            equity = None
            if roe and profit:
                equity = profit / (roe / 100.0)
            leverage = (assets / equity) if (assets and equity) else None
            implied_roe = (roa * leverage) if (roa is not None and leverage) else None
            rows.append(dict(
                bank=bank, period_label=period,
                roe_reported_pct=roe, roa_pct=roa,
                equity_implied_inr=equity, leverage_x=leverage,
                roe_implied_pct=implied_roe,
                gap_pp=(None if (implied_roe is None or roe is None) else implied_roe - roe),
                note="" if (implied_roe is None or roe is None or abs(implied_roe - roe) <= 0.5)
                     else "implied ROE differs from reported by more than 0.5pp - check the "
                          "equity and average-asset bases",
            ))
    return rows
