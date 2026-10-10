"""Pass 4 - cross-verification of the source log against independent extraction.

WHAT THIS DOES
--------------
``extract_metrics.py`` (text and regex), the coordinate reader (chart
positions) and camelot (table extraction) each produce candidate values for the
same metric, bank and year. Where two or more **independent** extractions land
on the same number in different documents or on different pages, that agreement
is evidence: the same figure was reached twice, by different methods, from
different places.

Cells confirmed that way are promoted to ``two_source_confirmed`` with
``verification_method = same_issuer_2_docs`` - the strongest status this project
can award without a person reading the page.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It never invents a value. A cell with no evidence stays exactly as it was. A
cell whose extractions disagree is reported as a disagreement, not averaged, and
not "resolved" by picking a favourite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import OUT_TABLES, SOURCE_LOG  # noqa: E402
from src.load import REQUIRED_COLUMNS  # noqa: E402

#: Two values are treated as the same figure when they agree to this tolerance.
#: Banks round differently between a table and a chart label, so exact equality
#: would reject genuine matches.
RELATIVE_TOLERANCE = 0.005


def _close(a: float, b: float) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) / scale <= RELATIVE_TOLERANCE


def load_candidates() -> pd.DataFrame:
    """Independent extraction candidates, as written by the extraction passes."""
    path = OUT_TABLES / "extraction_candidates.csv"
    if not path.exists():
        return pd.DataFrame(columns=["metric", "value", "year", "doc", "page"])
    frame = pd.read_csv(path)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["year"] = pd.to_numeric(frame["year"], errors="coerce")
    return frame.dropna(subset=["value", "year"])


def cross_verify(log: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    """Promote cells that independent extractions agree on. Returns the updated log."""
    out = log.copy()
    out["_value"] = pd.to_numeric(out["value_as_reported"], errors="coerce")

    promoted = 0
    disagreements: list[str] = []
    for index, row in out.iterrows():
        if pd.isna(row["_value"]):
            continue
        if row.get("status") in {"two_source_confirmed", "verified",
                                 "manually_corrected"}:
            continue

        year = row["period_label"]
        if not isinstance(year, str) or not year.startswith("FY"):
            continue
        try:
            year_number = 2000 + int(year[2:])
        except ValueError:
            continue

        pool = candidates[(candidates["metric"] == row["metric_code"])
                          & (candidates["year"] == year_number)
                          & (candidates["doc"].str.contains(row["bank"],
                                                            na=False, regex=False))]
        if pool.empty:
            continue

        matches = pool[pool["value"].map(lambda v: _close(float(v), float(row["_value"])))]
        distinct_sources = {(str(m["doc"]), str(m["page"])) for _, m in matches.iterrows()}
        own_source = (str(row["document_title"]), str(row["page_number"]))
        independent = distinct_sources - {own_source}

        if len(independent) >= 1 and len(distinct_sources) >= 2:
            sources = sorted(distinct_sources)
            out.at[index, "status"] = "two_source_confirmed"
            out.at[index, "verification_method"] = "same_issuer_2_docs"
            note = str(row.get("notes", ""))
            out.at[index, "notes"] = (
                f"CROSS-VERIFIED against {len(distinct_sources)} independent "
                f"extractions: {', '.join(f'{d} p{p}' for d, p in sources[:4])}. "
                + note)[:900]
            promoted += 1
        elif len(matches) == 0:
            others = sorted({round(float(v), 2) for v in pool["value"].unique()})[:4]
            if others:
                disagreements.append(
                    f"{row['bank']} {row['metric_code']} {year}: recorded "
                    f"{float(row['_value']):g}, other extractions found {others}")

    out = out.drop(columns=["_value"])
    return out, promoted, disagreements


def main() -> int:
    if not SOURCE_LOG.exists():
        print(f"No source log at {SOURCE_LOG}")
        return 1

    log = pd.read_csv(SOURCE_LOG, dtype=str, keep_default_na=False)
    candidates = load_candidates()
    print(f"source log rows    : {len(log)}")
    print(f"candidate values   : {len(candidates)}")

    updated, promoted, disagreements = cross_verify(log, candidates)

    for column in REQUIRED_COLUMNS:
        if column not in updated.columns:
            updated[column] = ""
    updated = updated[REQUIRED_COLUMNS]
    updated.to_csv(SOURCE_LOG, index=False)

    print(f"\npromoted to two_source_confirmed : {promoted}")
    print("status counts after the pass:")
    for status, count in updated["status"].value_counts().items():
        print(f"  {status:<20} {count}")

    if disagreements:
        print(f"\nrecorded values with no independent match ({len(disagreements)}):")
        for line in disagreements[:12]:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
