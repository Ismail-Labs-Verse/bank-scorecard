"""Chart generation for the bank scorecard study.

Every figure is written to ``outputs/charts/`` as a 200-dpi PNG.

Design system
-------------
A restrained three-colour palette (navy, gold, slate) on a light ground, one
fixed colour per bank, and colour is never the only carrier of meaning: each
bank also gets its own marker shape so the figures survive greyscale printing.
The HDFC merger is drawn on every time-series chart as a dotted vertical line,
because FY2024 is a transition year and reading the series without that marker
invites a false comparison.

Honesty rules built into this module
------------------------------------
* Figures drawn from values that have not been human-verified are stamped
  ``PRELIMINARY - UNVERIFIED EXTRACTION`` in the image itself.
* A chart whose inputs do not exist is **skipped with a printed reason**. It is
  never drawn empty, and missing data is never substituted with an estimate.
* The scorecard, pillar and sensitivity charts require trusted values for all
  three banks. While any bank is missing a metric, they do not render at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import BANKS, OUT_CHARTS, OUT_TABLES, SOURCE_LOG, WINDOW_PRIMARY

plt.rcParams.update({
    "figure.facecolor": "#FFFFFF",
    "axes.facecolor": "#FFFFFF",
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "axes.edgecolor": "#C9CED6",
    "axes.labelcolor": "#1B2A4A",
    "text.color": "#1B2A4A",
    "xtick.color": "#5A6473",
    "ytick.color": "#5A6473",
    "axes.grid": True,
    "grid.color": "#E4E7EC",
    "grid.linewidth": 0.7,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
NAVY = "#1B2A4A"
GOLD = "#D4AF37"
SLATE = "#6B7A8F"
LIGHT_GREY = "#F5F5F5"
GREY_TEXT = "#5A6473"

BANK_COLOR = {"SBI": NAVY, "HDFC": GOLD, "ICICI": SLATE}
BANK_MARKER = {"SBI": "o", "HDFC": "s", "ICICI": "^"}

PILLAR_COLOR = {"asset_quality": NAVY, "profit": GOLD, "efficiency": SLATE}

TITLE_SIZE, LABEL_SIZE, TICK_SIZE, NOTE_SIZE = 14, 10, 9, 8
DPI = 200

#: The HDFC merger completed on 1 July 2023, which falls inside FY2024.
MERGER_YEAR = "FY2024"
MERGER_LABEL = "HDFC merger\n1 Jul 2023"

PRELIMINARY_STAMP = "PRELIMINARY - UNVERIFIED EXTRACTION"
TRUSTED_STATUSES = {"verified", "two_source_confirmed"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _save(fig, name: str) -> Path:
    OUT_CHARTS.mkdir(parents=True, exist_ok=True)
    path = OUT_CHARTS / name
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    return path


def _stamp(fig, text: str = PRELIMINARY_STAMP) -> None:
    """Mark a figure as built from unverified values, inside the image."""
    fig.text(0.5, 0.5, text, fontsize=26, color=GOLD, alpha=0.16,
             ha="center", va="center", rotation=22, zorder=0)


def _title(ax, title: str, subtitle: str | None = None) -> None:
    """Left-aligned title with an optional explanatory subtitle beneath it.

    The pad is generous because the subtitle is drawn in axes coordinates just
    above the plot area; a tighter pad makes the two strings collide.
    """
    ax.set_title(title, fontsize=TITLE_SIZE, color=NAVY, loc="left", pad=30)
    if subtitle:
        ax.text(0.0, 1.012, subtitle, transform=ax.transAxes, fontsize=NOTE_SIZE,
                color=GREY_TEXT, ha="left", va="bottom")


def _merger_line(ax, years: list[str]) -> None:
    """Dotted vertical line + annotation marking the HDFC merger."""
    if MERGER_YEAR not in years:
        return
    position = years.index(MERGER_YEAR) - 0.5
    ax.axvline(position, color=GREY_TEXT, linestyle=":", linewidth=1.2, zorder=1)
    ax.annotate(MERGER_LABEL, xy=(position, 0.98), xycoords=("data", "axes fraction"),
                xytext=(6, 0), textcoords="offset points", fontsize=NOTE_SIZE,
                color=GREY_TEXT, va="top", ha="left")


def _load_trusted_metrics() -> pd.DataFrame:
    """Source-log rows a human has confirmed, ready to plot."""
    if not SOURCE_LOG.exists():
        return pd.DataFrame()
    log = pd.read_csv(SOURCE_LOG, dtype=str, keep_default_na=False)
    log["value_as_reported"] = pd.to_numeric(log["value_as_reported"], errors="coerce")
    trusted = log[log["status"].isin(TRUSTED_STATUSES) & log["value_as_reported"].notna()]
    return trusted[trusted["period_label"].isin(WINDOW_PRIMARY)].copy()


def _load_extracted_metrics() -> pd.DataFrame:
    """Extracted values that are not yet verified - plotted only with a stamp."""
    if not SOURCE_LOG.exists():
        return pd.DataFrame()
    log = pd.read_csv(SOURCE_LOG, dtype=str, keep_default_na=False)
    log["value_as_reported"] = pd.to_numeric(log["value_as_reported"], errors="coerce")
    rows = log[log["value_as_reported"].notna()]
    return rows[rows["period_label"].isin(WINDOW_PRIMARY)].copy()


# ---------------------------------------------------------------------------
# Coverage - the one figure that is always fully defensible
# ---------------------------------------------------------------------------
STATUS_RANK = {"verified": 4, "two_source_confirmed": 4, "auto_extracted": 2,
               "MANUAL_REQUIRED": 1, "conflict": 0, "UNVERIFIED": 1}

STATUS_COLOR = {4: NAVY, 2: GOLD, 1: "#E4E7EC", 0: "#C0392B"}
STATUS_LABEL = {4: "human-verified", 2: "extracted, unverified",
                1: "not found - manual", 0: "conflicting"}


def coverage_heatmap() -> Path | None:
    """Bank x metric grid showing how far each series has actually been verified.

    This is the honest companion to every other exhibit in the study: it says
    which cells exist, which are machine-extracted, and which are still blank.
    """
    if not SOURCE_LOG.exists():
        print("  skip coverage_heatmap: no source log")
        return None

    log = pd.read_csv(SOURCE_LOG, dtype=str, keep_default_na=False)
    if log.empty:
        print("  skip coverage_heatmap: source log is empty")
        return None

    log["rank"] = log["status"].map(lambda s: STATUS_RANK.get(s, 1))
    log["series"] = log["bank"] + " " + log["metric_name"].fillna(log["metric_code"])

    grid = log.pivot_table(index="series", columns="period_label", values="rank",
                           aggfunc="max")
    grid = grid.reindex(columns=[c for c in WINDOW_PRIMARY if c in grid.columns])
    grid = grid.sort_index()

    fig, ax = plt.subplots(figsize=(7.6, 5.4))
    for row in range(grid.shape[0]):
        for col in range(grid.shape[1]):
            value = grid.values[row, col]
            rank = 1 if pd.isna(value) else int(value)
            ax.add_patch(plt.Rectangle((col, row), 1, 1,
                                       facecolor=STATUS_COLOR.get(rank, "#E4E7EC"),
                                       edgecolor="#FFFFFF", linewidth=2))
            ax.text(col + 0.5, row + 0.5, STATUS_LABEL.get(rank, "")[:9],
                    ha="center", va="center", fontsize=6.5,
                    color="#FFFFFF" if rank in (4, 2, 0) else GREY_TEXT)

    ax.set_xlim(0, grid.shape[1])
    ax.set_ylim(0, grid.shape[0])
    ax.set_xticks([c + 0.5 for c in range(grid.shape[1])])
    ax.set_xticklabels(grid.columns, fontsize=TICK_SIZE)
    ax.set_yticks([r + 0.5 for r in range(grid.shape[0])])
    ax.set_yticklabels(grid.index, fontsize=TICK_SIZE)
    ax.grid(False)
    _title(ax, "Data verification coverage",
           "What exists, what is machine-extracted, and what is still missing")
    fig.tight_layout()
    return _save(fig, "coverage_heatmap.png")


# ---------------------------------------------------------------------------
# Trend charts
# ---------------------------------------------------------------------------
def trend_chart(metric_code: str, metric_name: str, unit: str = "") -> Path | None:
    """One metric, three banks, with the merger line and a preliminary stamp when
    the underlying values are not yet verified."""
    rows = _load_extracted_metrics()
    if rows.empty:
        print(f"  skip trend_{metric_code}: no values in the source log")
        return None

    data = rows[rows["metric_code"] == metric_code]
    if data.empty or data["bank"].nunique() < 2:
        print(f"  skip trend_{metric_code}: needs at least two banks with values")
        return None

    trusted = _load_trusted_metrics()
    preliminary = trusted.empty or not set(
        data["source_id"]).issubset(set(trusted.get("source_id", [])))

    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    years = [y for y in WINDOW_PRIMARY]
    for bank in BANKS:
        series = (data[data["bank"] == bank]
                  .drop_duplicates(subset=["period_label"])
                  .set_index("period_label")["value_as_reported"]
                  .reindex(years))
        if series.notna().sum() == 0:
            continue
        ax.plot(years, series.values, color=BANK_COLOR[bank],
                marker=BANK_MARKER[bank], markersize=6, linewidth=2.0, label=bank)
        for year, value in zip(years, series.values):
            if pd.notna(value):
                ax.annotate(f"{value:,.2f}", (year, value), textcoords="offset points",
                            xytext=(0, 7), ha="center", fontsize=7, color=GREY_TEXT)

    _merger_line(ax, years)
    ax.set_ylabel(f"{metric_name}{f' ({unit})' if unit else ''}", fontsize=LABEL_SIZE)
    ax.tick_params(labelsize=TICK_SIZE)
    ax.legend(frameon=False, fontsize=TICK_SIZE, ncol=3, loc="best")
    _title(ax, f"{metric_name}, FY2022-FY2026",
           "Source: bank annual reports" + ("  |  preliminary" if preliminary else ""))
    if preliminary:
        _stamp(fig)
    fig.tight_layout()
    return _save(fig, f"trend_{metric_code}.png")


# ---------------------------------------------------------------------------
# Scorecard-dependent exhibits
# ---------------------------------------------------------------------------
def hero_chart() -> Path | None:
    """Overall scorecard ranking over the window, one line per bank."""
    path = OUT_TABLES / "scorecard_primary_FY22_FY26.csv"
    if not path.exists():
        print("  skip hero_chart: no scorecard output (no trusted values yet)")
        return None
    scored = pd.read_csv(path, dtype=str, keep_default_na=False)
    if scored.empty or "overall" not in scored.columns:
        print("  skip hero_chart: scorecard is empty")
        return None
    scored["overall"] = pd.to_numeric(scored["overall"], errors="coerce")

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    years = sorted(scored["period_label"].unique())
    for bank in BANKS:
        series = (scored[scored["bank"] == bank]
                  .set_index("period_label")["overall"].reindex(years))
        if series.notna().sum() == 0:
            continue
        ax.plot(years, series.values, color=BANK_COLOR[bank],
                marker=BANK_MARKER[bank], markersize=7, linewidth=2.4, label=bank)
    _merger_line(ax, years)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Overall score (0-100, relative to that year)", fontsize=LABEL_SIZE)
    ax.tick_params(labelsize=TICK_SIZE)
    ax.legend(frameon=False, fontsize=TICK_SIZE, ncol=3, loc="best")
    _title(ax, "Overall scorecard score, FY2022-FY2026",
           "100 = best of the three that year, not good in absolute terms")
    fig.tight_layout()
    return _save(fig, "hero_chart.png")


def pillar_charts() -> list[Path]:
    """One chart per pillar: asset quality, profitability, efficiency."""
    path = OUT_TABLES / "scorecard_primary_FY22_FY26.csv"
    if not path.exists():
        print("  skip pillar charts: no scorecard output (no trusted values yet)")
        return []
    scored = pd.read_csv(path, dtype=str, keep_default_na=False)
    made: list[Path] = []
    for pillar, label in (("asset_quality", "Asset quality"),
                          ("profit", "Profitability"),
                          ("efficiency", "Efficiency")):
        if pillar not in scored.columns:
            continue
        frame = scored.copy()
        frame[pillar] = pd.to_numeric(frame[pillar], errors="coerce")
        if frame[pillar].notna().sum() == 0:
            continue
        fig, ax = plt.subplots(figsize=(7.6, 3.8))
        years = sorted(frame["period_label"].unique())
        for bank in BANKS:
            series = (frame[frame["bank"] == bank]
                      .set_index("period_label")[pillar].reindex(years))
            if series.notna().sum() == 0:
                continue
            ax.plot(years, series.values, color=BANK_COLOR[bank],
                    marker=BANK_MARKER[bank], markersize=6, linewidth=2.2, label=bank)
        _merger_line(ax, years)
        ax.set_ylim(0, 100)
        ax.set_ylabel("Score (0-100)", fontsize=LABEL_SIZE)
        ax.tick_params(labelsize=TICK_SIZE)
        ax.legend(frameon=False, fontsize=TICK_SIZE, ncol=3, loc="best")
        _title(ax, f"{label} pillar score", "Relative to the other two banks that year")
        fig.tight_layout()
        made.append(_save(fig, f"pillar_{pillar}.png"))
    if not made:
        print("  skip pillar charts: no pillar scores available")
    return made


def dupont_chart() -> Path | None:
    """Stacked bars: every bank's ROE split into ROA and leverage."""
    path = OUT_TABLES / "dupont.csv"
    if not path.exists():
        print("  skip dupont_chart: run the pipeline first")
        return None
    data = pd.read_csv(path, dtype=str, keep_default_na=False)
    for column in ("roa_pct", "leverage_x", "roe_reported_pct"):
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["roa_pct", "leverage_x"])
    if data.empty:
        print("  skip dupont_chart: no rows with both ROA and leverage")
        return None

    grouped = data.groupby("bank")[["roa_pct", "leverage_x"]].mean().reindex(BANKS).dropna()
    if grouped.empty:
        print("  skip dupont_chart: nothing to average")
        return None

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    positions = np.arange(len(grouped))
    ax.bar(positions, grouped["roa_pct"], width=0.5, color=GOLD, label="ROA (%)")
    ax.bar(positions, grouped["leverage_x"], width=0.5, bottom=grouped["roa_pct"],
           color=NAVY, label="Leverage (x)")
    for position, (bank, row) in zip(positions, grouped.iterrows()):
        total = row["roa_pct"] + row["leverage_x"]
        ax.text(position, row["roa_pct"] / 2, f"{row['roa_pct']:.2f}%",
                ha="center", va="center", fontsize=8, color=NAVY)
        ax.text(position, row["roa_pct"] + row["leverage_x"] / 2,
                f"{row['leverage_x']:.1f}x", ha="center", va="center",
                fontsize=8, color="#FFFFFF")
        ax.text(position, total + 0.4, f"ROE {row['roa_pct'] * row['leverage_x']:.1f}%",
                ha="center", va="bottom", fontsize=8, color=GREY_TEXT)
    ax.set_xticks(positions)
    ax.set_xticklabels(grouped.index, fontsize=TICK_SIZE)
    ax.set_ylabel("ROE = ROA x leverage", fontsize=LABEL_SIZE)
    ax.tick_params(labelsize=TICK_SIZE)
    ax.legend(frameon=False, fontsize=TICK_SIZE, loc="upper right")
    _title(ax, "Return on equity decomposed",
           "A bank can beat peers on ROA, on leverage, or both - the split matters")
    _stamp(fig)
    fig.tight_layout()
    return _save(fig, "dupont_chart.png")


def sensitivity_chart() -> Path | None:
    """How often each bank ranks first across the random weight simulations."""
    path = OUT_TABLES / "sensitivity_win_shares.csv"
    if not path.exists():
        print("  skip sensitivity_chart: no sensitivity output (no scorecard yet)")
        return None
    shares = pd.read_csv(path, dtype=str, keep_default_na=False)
    if shares.empty or "p_rank1" not in shares.columns:
        print("  skip sensitivity_chart: sensitivity table is empty")
        return None
    shares["p_rank1"] = pd.to_numeric(shares["p_rank1"], errors="coerce")

    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    shares = shares.sort_values("p_rank1")
    ax.barh(shares["bank"], shares["p_rank1"] * 100,
            color=[BANK_COLOR.get(b, SLATE) for b in shares["bank"]], height=0.55)
    for position, value in enumerate(shares["p_rank1"] * 100):
        ax.text(value + 1, position, f"{value:.1f}%", va="center", fontsize=9,
                color=GREY_TEXT)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of 10,000 random weightings where the bank ranks #1",
                  fontsize=LABEL_SIZE)
    ax.tick_params(labelsize=TICK_SIZE)
    _title(ax, "How robust is the winner to the weighting?",
           "Weights drawn from Dirichlet(1,1,1), seed 42")
    fig.tight_layout()
    return _save(fig, "sensitivity_chart.png")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def generate_all() -> list[Path]:
    """Build every figure the available data supports. Returns the paths written."""
    OUT_CHARTS.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []

    print("Generating charts")
    for builder in (coverage_heatmap, hero_chart, dupont_chart, sensitivity_chart):
        result = builder()
        if result:
            made.append(result)

    made.extend(pillar_charts())

    metrics = [
        ("gross_npa_pct", "Gross NPA", "%"),
        ("net_npa_pct", "Net NPA", "%"),
        ("net_profit_inr", "Net profit", "INR crore"),
        ("roa_pct", "Return on assets", "%"),
        ("roe_pct", "Return on equity", "%"),
    ]
    for code, label, unit in metrics:
        result = trend_chart(code, label, unit)
        if result:
            made.append(result)

    for path in made:
        print(f"  wrote {path.relative_to(ROOT)}")
    print(f"  {len(made)} chart(s) generated")
    return made


if __name__ == "__main__":
    generate_all()
