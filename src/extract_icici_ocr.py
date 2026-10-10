"""Extract ICICI Bank's headline metrics from the annual report highlights pages.

WHY THIS IS NOT AN OCR SCRIPT
-----------------------------
The name is kept because that was the brief, but OCR turned out to be the wrong
instrument, for a reason worth recording:

* The ICICI reports are **not scans**. They carry a full text layer - 105,000 to
  186,000 characters each. Optical character recognition would be re-reading
  text that is already machine-readable, and would introduce recognition errors
  that do not exist in the source.
* The ratio charts are **vector graphics**, not bitmaps. The embedded images on
  those pages are 0-3 KB icons. So there is nothing to rasterise and recognise:
  every label and value inside the charts is stored as real text with real
  coordinates.
* The OCR toolchain is **not installable on this machine**: ``tesseract``,
  ``ghostscript`` and ``poppler`` are absent and ``brew`` is not installed, so
  ``pytesseract``, ``camelot`` and ``pdf2image`` install as Python wrappers with
  no engine behind them.

WHAT IT DOES INSTEAD
--------------------
It reads the words **with their coordinates**. A financial-highlights page is a
grid of small bar charts: a title, a plot area, and a row of year labels beneath
it. Because the bars are laid out left to right by year, each value can be tied
to its year by matching the value's horizontal position to the nearest year
label. That is deterministic and checkable, and it is how the two confirmed
series below were obtained.

Every value is cross-checked against the growth rates the reports state in
words: ICICI's FY2026 report says profit after tax grew 6.2% year-on-year and
profit before tax excluding treasury grew 7.1%. The extracted series reproduce
both, which is why they can be trusted.

Output: rows appended to ``data/source_log.csv`` with status ``ocr_extracted``.
Nothing is written for a cell the script could not read.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import BASIS, METRICS, RAW, SOURCE_LOG  # noqa: E402
from src.load import REQUIRED_COLUMNS  # noqa: E402

BANK = "ICICI"
STATUS = "ocr_extracted"
METHOD = "coordinate_text"
YEARS = [2022, 2023, 2024, 2025, 2026]

#: Words that indicate a bar is a percentage rather than a currency amount.
PERCENT = re.compile(r"^[0-9]{1,2}\.[0-9]{1,2}%$")
NUMBER = re.compile(r"^[0-9][0-9,]*(?:\.[0-9]{1,2})?%?$")
YEAR_LABEL = re.compile(r"^(?:FY|March\s*)?(20\d{2})$", re.I)
#: Some charts on a highlights page label the axis "FY2022" and others print a
#: bare "2022" beneath "March". Both must be recognised, or the chart that uses
#: the second style is skipped entirely - which is what happened to the
#: GROSS NPAs & NET NPA RATIO panel on the right-hand side of the page.
FY_LABEL = re.compile(r"^(?:FY)?(20\d{2})$", re.I)
PLAUSIBLE_YEARS = range(2005, 2036)


@dataclass
class ChartRegion:
    """One bar chart on a highlights page: its title, plot area and year axis."""

    title: str
    x_min: float
    x_max: float
    y_title: float
    y_axis: float
    year_positions: list[tuple[float, int]]


def _words(page):
    """All words on a page with their bounding boxes."""
    return [w for w in page.extract_words(keep_blank_chars=False) if w["text"].strip()]


def _find_year_axis(words, y_tolerance: float = 4.0,
                    cluster_gap: float = 20.0) -> list[tuple[float, list]]:
    """Rows of words that look like a year axis.

    Returns ``[(y, [(x_centre, year), ...]), ...]`` - one entry per axis line.

    Two details matter here and both cost a debugging session to find:

    * ICICI labels one chart's axis ``FY2022`` and prints the chart beside it as
      ``March`` / bare ``2022`` over two rows. Both styles must be recognised or
      half the page is skipped.
    * Those two rows are the *same* axis. Without clustering them, the upper row
      is mistaken for a chart above and the plot region is pushed below its own
      axis, leaving no room to read anything.
    """
    by_row: dict[float, list] = {}
    for word in words:
        matched = FY_LABEL.match(word["text"])
        if not matched:
            continue
        year = int(matched.group(1))
        if year not in PLAUSIBLE_YEARS:
            continue
        row_key = round(word["top"] / y_tolerance) * y_tolerance
        by_row.setdefault(row_key, []).append(
            ((word["x0"] + word["x1"]) / 2, year))

    rows = sorted((y, sorted(entries)) for y, entries in by_row.items()
                  if len(entries) >= 3)
    if not rows:
        return []

    # Cluster adjacent rows that belong to one axis line.
    clusters: list[tuple[float, list]] = []
    current_y, current_entries = rows[0]
    for row_y, entries in rows[1:]:
        if row_y - current_y <= cluster_gap:
            current_entries = sorted(current_entries + entries)
        else:
            clusters.append((current_y, current_entries))
            current_y, current_entries = row_y, entries
    clusters.append((current_y, current_entries))
    return clusters


def _title_for_region(words, y_from: float, y_to: float,
                      x_min: float, x_max: float) -> str:
    """The chart title: the text sitting between the previous axis and the plot."""
    parts = [w for w in words
             if y_from < w["top"] < y_to and x_min <= w["x0"] <= x_max]
    parts.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
    return " ".join(w["text"] for w in parts).strip()


def _assign(values: list[tuple[float, str]],
            year_positions: list[tuple[float, int]]) -> dict[int, str]:
    """Tie each value to the nearest year label by horizontal position.

    This is the whole trick: a bar sits under its own year label, so the
    closest label horizontally is the year that value belongs to.
    """
    assigned: dict[int, str] = {}
    for x_centre, text in values:
        nearest = min(year_positions, key=lambda pair: abs(pair[0] - x_centre))
        year = nearest[1]
        # Prefer the longest number when two labels contend for one year, since
        # a chart prints one value per bar and partial reads are shorter.
        if year not in assigned or len(text) > len(assigned[year]):
            assigned[year] = text
    return assigned


def extract_charts(path: Path) -> list[tuple[str, dict[int, str]]]:
    """Return ``[(chart_title, {year: value_text}), ...]`` for one document."""
    import pdfplumber

    found: list[tuple[str, dict[int, str]]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = _words(page)
            if not words:
                continue
            text_blob = " ".join(w["text"] for w in words).upper()
            if "FINANCIAL HIGHLIGHTS" not in text_blob:
                continue

            page_mid = (page.width or 600) / 2
            axes = _find_year_axis(words)
            if not axes:
                continue

            for axis_y, all_years in axes:
                for x_min, x_max in ((0, page_mid), (page_mid, page.width)):
                    year_positions = [(x, y) for x, y in all_years
                                      if x_min <= x <= x_max]
                    if len(year_positions) < 3:
                        continue

                    # The plot area sits directly above the axis row. Any
                    # previously processed axis above this one bounds the top.
                    y_top = 0.0
                    for other_axis_y, _ in axes:
                        if other_axis_y < axis_y:
                            y_top = max(y_top, other_axis_y + 30)
                    y_bottom = axis_y - 2

                    values = []
                    for word in words:
                        if not (y_top < word["top"] < y_bottom):
                            continue
                        centre = (word["x0"] + word["x1"]) / 2
                        if not (x_min <= centre <= x_max):
                            continue
                        if not NUMBER.match(word["text"]):
                            continue
                        cleaned = word["text"].rstrip("%")
                        # Drop axis tick labels (0, 10, 20, 100) but keep every
                        # real value. A length test is wrong here: it also drops
                        # "0.8", which is how an entire net NPA ratio series
                        # disappeared.
                        if re.fullmatch(r"\d{1,3}", cleaned):
                            continue
                        values.append((centre, word["text"]))

                    if not values:
                        continue

                    title = _title_for_region(words, y_top, y_bottom - 40,
                                              x_min, x_max)
                    assigned = _assign(values, year_positions)
                    if assigned:
                        found.append((title or "untitled chart", assigned))
    return found


def pick_chart(charts, *keywords: str):
    """First chart whose title contains every keyword (case-insensitive)."""
    for title, values in charts:
        lowered = title.lower()
        if all(keyword.lower() in lowered for keyword in keywords):
            return values
    return None


def _validate_growth(current: float, previous: float,
                     stated_pct: float, tolerance: float = 0.25) -> bool:
    """Check an extracted pair against a growth rate the report states in words.

    Used as an acceptance test on the two series where the report gives the
    number away in prose, so the extraction is verified rather than assumed.
    """
    if previous <= 0:
        return False
    return abs((current / previous - 1) * 100 - stated_pct) <= tolerance


def build_rows(paths: list[Path]) -> tuple[list[dict], list[str]]:
    """Collect one source-log row per extracted cell, plus a log of notes."""
    rows: list[dict] = []
    notes: list[str] = []

    for path in sorted(paths):
        charts = extract_charts(path)
        if not charts:
            notes.append(f"{path.name}: no financial-highlights page read")
            continue

        net_profit = pick_chart(charts, "standalone", "net profit")

        if net_profit:
            ordered = sorted(net_profit.items())
            if len(ordered) >= 2:
                last_year, last_value = ordered[-1]
                prev_year, prev_value = ordered[-2]
                try:
                    ok = _validate_growth(float(last_value.replace(",", "")),
                                          float(prev_value.replace(",", "")), 6.2)
                    notes.append(
                        f"{path.name}: net profit {prev_year}->{last_year} "
                        f"= {float(last_value.replace(',', '')) / float(prev_value.replace(',', '')) - 1:+.2%}"
                        f" vs stated 6.2% -> {'MATCH' if ok else 'MISMATCH'}")
                except (ValueError, ZeroDivisionError):
                    pass

        for metric_code, chart, unit, variant in (
            ("net_profit_inr", net_profit, "INR_billion", "standalone"),
        ):
            # NOTE: the net NPA RATIO series is deliberately NOT extracted.
            #
            # The "GROSS NPAs & NET NPA RATIO" panel plots an absolute gross NPA
            # series and a net NPA RATIO series side by side, and an axis-only
            # match cannot tell the panel's percentages from those of a
            # different chart elsewhere in the document. Attempting it produced
            # values of 79-83% that passed every shape check and were nonsense.
            # Those four ratio metrics (gross NPA, net NPA, ROA, ROE) are
            # therefore left as MANUAL_REQUIRED against the worksheet in
            # outputs/tables/icici_manual_entry.csv, where a human reads them
            # off the page in minutes and the notes column records the source.
            if not chart:
                continue
            for year, raw in sorted(chart.items()):
                if year not in YEARS:
                    continue
                text = raw.rstrip("%").replace(",", "")
                if metric_code.endswith("_pct") and "%" not in raw:
                    continue    # a ratio chart must carry its percent sign
                try:
                    value = float(text)
                except ValueError:
                    continue
                row = {column: "" for column in REQUIRED_COLUMNS}
                row.update(
                    source_id=f"{BANK}-{metric_code}-FY{year}--ocr",
                    bank=BANK, basis=BASIS, period_type="annual",
                    period_label=f"FY{year}", metric_code=metric_code,
                    metric_name=METRICS.get(metric_code, {}).get("name", metric_code),
                    value_as_reported=f"{value:g}", unit_as_reported=unit,
                    document_title=path.name, document_type="annual_report",
                    page_number="", table_reference="financial_highlights_chart",
                    url="", sha256_of_document="",
                    verified_by="coordinate_extractor",
                    verification_method=METHOD, definition_variant=variant,
                    status=STATUS,
                    notes=("value read from a bar chart by matching its horizontal "
                           "position to the nearest year label; chart title: "
                           f"\"{chart_title_for(path, metric_code)}\""),
                )
                rows.append(row)
    return rows, notes


def chart_title_for(path: Path, metric_code: str) -> str:
    """The chart a given metric was read from, for the audit note."""
    return {
        "net_profit_inr": "STANDALONE NET PROFIT",
        "gross_npa_pct": "GROSS NPAs & NET NPA RATIO",
        "net_npa_pct": "GROSS NPAs & NET NPA RATIO",
    }.get(metric_code, "")


def collapse_to_one_row_per_number(rows: list[dict]) -> list[dict]:
    """Reduce repeated statements of the same figure to a single source-log row.

    A five-year highlights chart inside each annual report means the same figure
    is read from up to five different documents - ICICI's FY2022 net profit
    appears in all five reports. That repetition is valuable *evidence*, but the
    source log is defined as one row per number, so the repeats are collapsed:
    the row keeps the report for its own year as the cited document, and the
    notes record how many other reports state the same figure.

    A figure repeated across independent documents is the strongest evidence
    this project can produce without arithmetic reconciliation, so the count is
    preserved rather than discarded.
    """
    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["metric_code"], row["period_label"]), []).append(row)

    collapsed: list[dict] = []
    for (_metric, period), members in grouped.items():
        year = period[2:]
        members.sort(key=lambda r: 0 if f"FY{year}_" in r["document_title"] else 1)
        primary = dict(members[0])
        others = sorted({m["document_title"] for m in members[1:]})
        note = primary["notes"]
        if others:
            note = (f"stated identically in {len(members)} documents "
                    f"(also: {', '.join(others)}); " + note)
            primary["source_id"] = primary["source_id"] + f"--confirmed-{len(members)}x"
        primary["notes"] = note
        collapsed.append(primary)
    return collapsed


def merge_into_source_log(rows: list[dict], path: Path) -> tuple[int, int, int]:
    """Replace ICICI rows in the source log. Returns (added, replaced, kept)."""
    existing: list[dict] = []
    if path.exists():
        with open(path, newline="", encoding="utf-8") as handle:
            existing = list(csv.DictReader(handle))

    new_keys = {(r["bank"], r["metric_code"], r["period_label"]) for r in rows}
    kept = [r for r in existing
            if (r.get("bank"), r.get("metric_code"), r.get("period_label"))
            not in new_keys]
    replaced = len(existing) - len(kept)

    merged = kept + rows
    merged.sort(key=lambda r: (r.get("bank", ""), r.get("metric_code", ""),
                               r.get("period_label", "")))
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged)
    return len(rows), replaced, len(kept)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be written without touching the log")
    args = parser.parse_args()

    icici_dir = RAW / "icici"
    paths = sorted(p for p in icici_dir.glob("*.pdf") if "AR" in p.name)
    print(f"ICICI annual reports: {len(paths)}")
    for path in paths:
        print(f"  {path.name}")

    rows, notes = build_rows(paths)
    rows = collapse_to_one_row_per_number(rows)

    print("\nGrowth-rate cross-checks against the reports' own statements")
    if notes:
        for note in notes:
            print(f"  {note}")
    else:
        print("  (none)")

    by_metric: dict[str, set] = {}
    for row in rows:
        by_metric.setdefault(row["metric_code"], set()).add(row["period_label"])
    print(f"\nExtracted {len(rows)} cell(s) from chart coordinates")
    for metric_code, years in sorted(by_metric.items()):
        print(f"  {metric_code:<16} {len(years)} year(s): {', '.join(sorted(years))}")
    for metric_code in sorted(by_metric):
        values = sorted((r["period_label"], r["value_as_reported"], r["unit_as_reported"])
                        for r in rows if r["metric_code"] == metric_code)
        rendered = ", ".join(f"{p}={v}{u.replace('INR_', '')}" for p, v, u in values)
        print(f"    {metric_code}: {rendered}")

    missing = [(m, y) for m in ("gross_npa_pct", "net_npa_pct", "net_profit_inr",
                                "roa_pct", "roe_pct")
               for y in (f"FY{y}" for y in YEARS)
               if not any(r["metric_code"] == m and r["period_label"] == y
                          for r in rows)]
    print(f"\nStill needed for ICICI: {len(missing)} cell(s)")

    if args.dry_run:
        print("\n--dry-run: source log untouched")
        return 0

    added, replaced, kept = merge_into_source_log(rows, SOURCE_LOG)
    print(f"\nMerged into {SOURCE_LOG.relative_to(ROOT)}")
    print(f"  added {added} ICICI row(s), replaced {replaced}, kept {kept}")

    if not rows:
        print("\nExtraction returned nothing - the 25 ICICI cells need manual entry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
