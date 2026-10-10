"""config.py - the single source of truth for every constant in this project.

Nothing in this project may hard-code a bank name, a colour, a weight or a seed
anywhere else. If it is a decision, it lives here, so it can be audited in one
place and changed in one place.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SOURCE_LOG = ROOT / "data" / "source_log.csv"
OUT_TABLES = ROOT / "outputs" / "tables"
OUT_CHARTS = ROOT / "outputs" / "charts"
OUT_TABLEAU = ROOT / "outputs" / "tableau"
OUT_MANIFEST = ROOT / "outputs" / "manifest.json"

BANKS = ["SBI", "HDFC", "ICICI"]

# Rule: all three banks are compared on STANDALONE financials, never consolidated.
BASIS = "standalone"

# Primary scorecard window, and the merger-clean robustness panel.
WINDOW_PRIMARY = [f"FY{y}" for y in range(2022, 2027)]   # FY2022..FY2026
WINDOW_CLEAN = [f"FY{y}" for y in range(2024, 2027)]     # FY2024..FY2026
QUARTER_SNAPSHOT = "Q1FY2027"   # ratios only, never pooled with annual flows

# HDFC Bank absorbed HDFC Ltd on 1 July 2023, so FY2024 is a transition year.
HDFC_MERGER_DATE = "2023-07-01"

SEED = 42

# ---------------------------------------------------------------------------
# Scoring policy.
#
# When True, machine-extracted values (status ``auto_extracted`` /
# ``ocr_extracted``) are treated as usable by the scoring layer even though no
# human has checked them against a page.
#
# This is OFF by default, and turning it on is a deliberate, visible decision:
# those values are known to contain errors - for example SBI's FY2023 net profit
# of INR 2,258 crore against the INR 50,232 crore its annual report states - and
# every score, ranking and chart downstream inherits them. Set it to False to
# require human verification before anything enters the scorecard.
# ---------------------------------------------------------------------------
ALLOW_UNVERIFIED_SCORING = False

# NOTE ON THIS SWITCH (measured, not assumed):
# With it set to False the pipeline has 0 score-eligible rows and produces no
# scorecard at all - no overall scores, no pillar scores, no weight
# simulations and therefore no hero chart, no pillar charts and no sensitivity
# chart. That is the honest consequence of requiring human verification when
# only one of 80 values has been checked against its page.
#
# It is therefore True while the extracted values remain provisional, and
# setting it to False is the single line that locks the study down once the
# review in data/source_log.csv is complete.

#: Statuses that always count as checked. ``manually_corrected`` is a value a
#: person read off the page and replaced, which is the strongest evidence this
#: project records.
TRUSTED_STATUSES = {"verified", "two_source_confirmed", "manually_corrected"}
if ALLOW_UNVERIFIED_SCORING:
    TRUSTED_STATUSES |= {"auto_extracted", "ocr_extracted"}
N_SENSITIVITY_DRAWS = 10_000

# Pillar weights: the author's judgement, not a fact. This is exactly what the
# sensitivity test measures, so they are declared here rather than hidden in code.
PILLAR_WEIGHTS = {"asset_quality": 0.35, "profit": 0.40, "efficiency": 0.25}

# ---------------------------------------------------------------------------
# Metric registry.
#   pillar=None  -> reported for context, NEVER scored (this is where every
#                   absolute rupee amount lives; scoring them would just rank
#                   the banks by size).
#   direction    -> +1 higher is better, -1 lower is better, 0 no clear direction.
# ---------------------------------------------------------------------------
METRICS = {
    # --- asset quality (bad loans) ---
    "gross_npa_pct":    dict(name="Gross NPA %", pillar="asset_quality", direction=-1, unit="pct"),
    "net_npa_pct":      dict(name="Net NPA %", pillar="asset_quality", direction=-1, unit="pct"),
    "pcr_pct":          dict(name="Provision Coverage Ratio", pillar="asset_quality", direction=1, unit="pct"),
    "slippage_pct":     dict(name="Slippage ratio", pillar="asset_quality", direction=-1, unit="pct"),
    "credit_cost_pct":  dict(name="Credit cost", pillar="asset_quality", direction=-1, unit="pct"),

    # --- profit ---
    "nim_pct":          dict(name="Net interest margin", pillar="profit", direction=1, unit="pct"),
    "roa_pct":          dict(name="Return on assets", pillar="profit", direction=1, unit="pct"),
    "roe_pct":          dict(name="Return on equity", pillar="profit", direction=1, unit="pct"),
    "profit_growth_pct": dict(name="Profit growth YoY", pillar="profit", direction=1, unit="pct"),

    # --- efficiency ---
    "cost_to_income_pct": dict(name="Cost-to-income", pillar="efficiency", direction=-1, unit="pct"),
    "opex_to_assets_pct": dict(name="Operating expense ratio", pillar="efficiency", direction=-1, unit="pct"),

    # --- context only: never scored (size, or no clear good direction) ---
    "net_profit_inr":   dict(name="Net profit", pillar=None, direction=1, unit="INR_crore"),
    "nii_inr":          dict(name="Net interest income", pillar=None, direction=1, unit="INR_crore"),
    "other_income_inr": dict(name="Other income", pillar=None, direction=1, unit="INR_crore"),
    "opex_inr":         dict(name="Operating expenses", pillar=None, direction=-1, unit="INR_crore"),
    "provisions_inr":   dict(name="Provisions and contingencies", pillar=None, direction=-1, unit="INR_crore"),
    "tax_inr":          dict(name="Tax expense", pillar=None, direction=-1, unit="INR_crore"),
    "total_assets_inr": dict(name="Total assets", pillar=None, direction=1, unit="INR_crore"),
    "advances_inr":     dict(name="Gross advances", pillar=None, direction=1, unit="INR_crore"),
    "deposits_inr":     dict(name="Deposits", pillar=None, direction=1, unit="INR_crore"),
    "non_interest_income_share_pct": dict(name="Non-interest income share", pillar=None, direction=0, unit="pct"),
    "crar_pct":         dict(name="CRAR", pillar=None, direction=1, unit="pct"),
    "cet1_pct":         dict(name="CET1 ratio", pillar=None, direction=1, unit="pct"),
}

def scored_metrics():
    """Metrics that are allowed to enter the scorecard."""
    return {k: v for k, v in METRICS.items() if v["pillar"] is not None}

def pillar_of(metric_code):
    return METRICS.get(metric_code, {}).get("pillar")

def direction_of(metric_code):
    return METRICS.get(metric_code, {}).get("direction", 0)

# Unit conversion to the two canonical units: 'pct' and 'INR_crore'.
UNIT_TO_CRORE = {
    "INR_crore": 1.0,
    "INR_lakh_crore": 100_000.0,   # 1 lakh crore = 100,000 crore
    "INR_billion": 100.0,          # 1 billion = 100 crore
    "INR_million": 0.1,            # 10 million = 1 crore
}
ACCEPTED_UNITS = ["pct", "ratio"] + list(UNIT_TO_CRORE.keys())
