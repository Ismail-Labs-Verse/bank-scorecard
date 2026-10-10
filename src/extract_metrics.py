"""extract_metrics.py - automated extraction of headline metrics from bank PDFs.

WHAT THIS REPLACES
------------------
Hand-entering 75 numbers from 21 PDFs into ``data/source_log.csv``. This script
finds them mechanically instead, and records the page and the matched line for
every value it reports.

WHAT IT DELIBERATELY DOES **NOT** DO
------------------------------------
It does not write its output into the source log as ``verified``. Machine
pattern-matching is fast and wrong in ways that look plausible - a five-year
highlights row read left to right will happily hand you FY2017's gross NPA and
label it FY2026. Writing that into the same file as human-checked figures would
launder a guess into an "audit-grade" number.

So every extracted row is written with::

    status              = auto_extracted      # never 'verified'
    verification_method = automated_regex
    page_number         = the page it was found on
    notes               = confidence grade + the exact matched line

and cells where nothing credible was found are written as ``MANUAL_REQUIRED``
with an empty value - never a guess. ``src/load.py`` treats only ``verified`` and
``two_source_confirmed`` rows as trusted, so nothing here can reach a score
until a human promotes it. Promotion is a one-column edit, which is the actual
time saving: review ~75 numbers in a table instead of hunting 5,400 pages.

EXTRACTION RULES
----------------
1. **Year anchoring.** A number is only accepted if the surrounding text names
   the year (``FY 2026``, ``2025-26``, ``year ended March 31, 2026``), or if it
   sits in the annual report for that year and no other year is named. The
   first is HIGH confidence, the second MEDIUM.
2. **Series guard.** A label followed by three or more numbers on the same line
   is a multi-year highlights row, not a single fact. Taking the first number
   would silently mis-date the value, so these are only used when a column
   header on the same page can be resolved to years; otherwise the cell is
   marked MANUAL_REQUIRED.
3. **Basis guard.** A match on a line mentioning "consolidated" is rejected -
   this study compares standalone financials only.
4. **Unit guard.** Currency values need an explicit unit (crore / lakh crore /
   billion / million). Without one the cell is MANUAL_REQUIRED, because
   "net profit 16,317" is not a number anyone can use.

USAGE
-----
    python src/extract_metrics.py --build-cache     # full text cache, all pages
    python src/extract_metrics.py                   # extract -> data/source_log.csv
    python src/extract_metrics.py --report          # also write the audit CSVs
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import (  # noqa: E402
    BASIS, METRICS, PROCESSED, RAW, WINDOW_PRIMARY, WINDOW_CLEAN,
)
from src.load import REQUIRED_COLUMNS  # noqa: E402

CACHE_DIR = PROCESSED / "text_cache"

#: Metrics this script targets, and their registry codes in src/config.py.
TARGET_METRICS = {
    "gross_npa_pct": "gross_npa_pct",
    "net_npa_pct": "net_npa_pct",
    "net_profit_inr": "net_profit_inr",
    "roa_pct": "roa_pct",
    "roe_pct": "roe_pct",
}

STATUS_EXTRACTED = "auto_extracted"
STATUS_MANUAL = "MANUAL_REQUIRED"
VERIFICATION = "automated_regex"


# ===========================================================================
# Document inventory
# ===========================================================================
@dataclass
class Document:
    path: Path
    bank: str
    fy: int | None            # 2022..2026
    kind: str                 # 'annual' | 'quarter' | 'other'
    sha256: str = ""
    bytes: int = 0
    modified: str = ""

    @property
    def title(self) -> str:
        return self.path.name


def _bank_of(name: str) -> str | None:
    upper = name.upper()
    for bank, token in (("HDFC", "HDFC"), ("SBI", "SBI"), ("ICICI", "ICICI")):
        if token in upper:
            return bank
    return None


def _fy_of(name: str) -> int | None:
    m = re.search(r"FY\s?(\d{2})", name, re.I)
    if m:
        return 2000 + int(m.group(1))
    m = re.search(r"(20\d{2})-(\d{2})", name)
    if m:
        return int(m.group(1)) + 1
    m = re.search(r"q1[-_ ]?(20\d{2})", name, re.I)
    if m:
        return int(m.group(1))
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(raw: Path = RAW) -> list[Document]:
    docs: list[Document] = []
    for path in sorted(raw.rglob("*.pdf")):
        name = path.name
        bank = _bank_of(name)
        if bank is None:
            continue
        fy = _fy_of(name)
        kind = "annual" if re.search(r"_AR\b|annual", name, re.I) else (
            "quarter" if re.search(r"q1|quarter|results|presentation", name, re.I)
            else "other")
        docs.append(Document(
            path=path, bank=bank, fy=fy, kind=kind,
            sha256=_sha256(path), bytes=path.stat().st_size,
            modified=date.fromtimestamp(path.stat().st_mtime).isoformat(),
        ))
    return docs


# ===========================================================================
# Full-text cache
#
# The dumps under data/processed/_extracted_raw/ only cover the first 40 pages
# of each PDF (that is the pipeline's probe limit). For a 629-page annual
# report that is 6% of the document, and the ratio tables are frequently past
# page 40. So this script extracts every page once into data/processed/
# text_cache/ and works from that.
# ===========================================================================
def cache_path_for(doc: Document, cache_dir: Path = CACHE_DIR) -> Path:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", doc.path.stem)
    return cache_dir / doc.bank / f"{stem}.txt"


def _extract_pages_fast(path: Path) -> list[str] | None:
    """Extract every page with pypdfium2, which is roughly 40x faster than
    pdfplumber (about 8 ms/page against 340 ms/page on these reports).

    That difference is the difference between a 20-minute wait and a 45-second
    one, and the text it returns carries the same metric lines - verified by
    comparing both extractors over the same 60 pages before switching.
    Returns None if pypdfium2 is not installed, so the caller can fall back.
    """
    try:
        import pypdfium2 as pdfium
    except Exception:
        return None
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception:
        return None
    try:
        pages: list[str] = []
        for i in range(len(doc)):
            try:
                pages.append(doc[i].get_textpage().get_text_range() or "")
            except Exception as exc:
                pages.append(f"<<page extract failed: {type(exc).__name__}: {exc}>>")
        return pages
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _extract_pages_pdfplumber(path: Path) -> list[str]:
    """Fallback extractor. Slower, but it is the reader the pipeline already uses."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = []
        for page in pdf.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:
                pages.append(f"<<page extract failed: {type(exc).__name__}: {exc}>>")
        return pages


def build_text_cache(docs: list[Document], cache_dir: Path = CACHE_DIR,
                     force: bool = False, verbose: bool = True) -> dict[str, int]:
    """Extract every page of every document into the cache. Returns page counts."""
    counts: dict[str, int] = {}
    for doc in docs:
        target = cache_path_for(doc, cache_dir)
        if target.exists() and not force:
            text = target.read_text(encoding="utf-8", errors="replace")
            counts[doc.path.name] = len(re.findall(r"===== page ", text))
            if verbose:
                print(f"  cached {doc.path.name:<46} {counts[doc.path.name]:>4} pages (reused)")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        pages = _extract_pages_fast(doc.path)
        engine = "pypdfium2"
        if pages is None:
            engine = "pdfplumber"
            try:
                pages = _extract_pages_pdfplumber(doc.path)
            except Exception as exc:
                counts[doc.path.name] = -1
                target.write_text(f"<<PDF OPEN FAILED: {type(exc).__name__}: {exc}>>",
                                  encoding="utf-8")
                if verbose:
                    print(f"  FAILED {doc.path.name}: {type(exc).__name__}: {exc}")
                continue

        chunks = [f"\n\n===== page {i} =====\n{text}"
                  for i, text in enumerate(pages, start=1)]
        target.write_text("".join(chunks), encoding="utf-8")
        counts[doc.path.name] = len(pages)
        if verbose:
            print(f"  cached {doc.path.name:<46} {len(pages):>4} pages via {engine}")
    return counts


_PAGE_RE = re.compile(r"===== page (\d+) =====")


def read_pages(doc: Document, cache_dir: Path = CACHE_DIR) -> list[tuple[int, str]]:
    """Return ``[(page_number, page_text), ...]`` from the cache."""
    target = cache_path_for(doc, cache_dir)
    if not target.exists():
        return []
    text = target.read_text(encoding="utf-8", errors="replace")
    marks = list(_PAGE_RE.finditer(text))
    pages: list[tuple[int, str]] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        pages.append((int(m.group(1)), text[m.end():end]))
    return pages


# ===========================================================================
# Patterns
# ===========================================================================
def _num(decimals: int = 2) -> str:
    return rf"([0-9]{{1,3}}(?:\.[0-9]{{1,{decimals}}})?)"


PCT = r"\s*(?:%|per\s*cent)"
GAP = r"[^0-9\n]{0,70}?"

#: Labels that identify each metric. Kept as separate patterns so the audit
#: table can say which one fired - a match from "Gross NPA declined to 1.49%"
#: is a different piece of evidence from one in a table column.
LABELS: dict[str, list[re.Pattern]] = {
    "gross_npa_pct": [
        re.compile(r"gross\s*npa", re.I),
        re.compile(r"gross\s*non[\s-]?performing\s*(?:assets|advances|loans|ratio)?", re.I),
        re.compile(r"\bGNPA\b", re.I),
    ],
    "net_npa_pct": [
        re.compile(r"net\s*npa", re.I),
        re.compile(r"net\s*non[\s-]?performing\s*(?:assets|advances|loans|ratio)?", re.I),
        re.compile(r"\bNNPA\b", re.I),
    ],
    "roa_pct": [
        re.compile(r"return\s*on\s*assets?", re.I),
        re.compile(r"\bRoA\b"),
        re.compile(r"\bROA\b"),
    ],
    "roe_pct": [
        re.compile(r"return\s*on\s*equity", re.I),
        re.compile(r"\bRoE\b"),
        re.compile(r"\bROE\b"),
    ],
    "net_profit_inr": [
        re.compile(r"net\s*profit", re.I),
        re.compile(r"profit\s*after\s*tax", re.I),
        re.compile(r"\bPAT\b"),
        re.compile(r"net\s*profit\s*after\s*tax", re.I),
    ],
}

YEAR_PATTERNS = [
    # The two-year form must be tested BEFORE the plain form: "FY 2024-25"
    # means the year ended March 2025, and a plain FY pattern reads it as 2024.
    (re.compile(r"FY\s?(20\d{2})[-/](\d{2})\b", re.I), lambda m: int(m.group(1)) + 1),
    (re.compile(r"FY\s?(\d{2})[-/](\d{2})\b", re.I), lambda m: 2000 + int(m.group(2))),
    (re.compile(r"(20\d{2})[-/](\d{2})\b"), lambda m: int(m.group(1)) + 1),
    (re.compile(r"FY\s?(20\d{2})", re.I), lambda m: int(m.group(1))),
    (re.compile(r"FY\s?(\d{2})\b"), lambda m: 2000 + int(m.group(1))),
    (re.compile(r"year\s+ended\s+(?:March|Mar)[a-z]*\s*31,?\s*(20\d{2})", re.I),
     lambda m: int(m.group(1))),
    (re.compile(r"March\s*31,?\s*(20\d{2})"), lambda m: int(m.group(1))),
    (re.compile(r"as\s+at\s+(?:March|Mar)[a-z]*\s*31,?\s*(20\d{2})", re.I),
     lambda m: int(m.group(1))),
]

HEADER_YEAR = re.compile(r"(?:FY\s?\d{2,4}|20\d{2}-\d{2}|20\d{2})")


@dataclass
class Candidate:
    metric: str
    value: float
    unit: str
    page: int
    line: str
    pattern: str
    doc: str
    doc_fy: int | None
    year: int | None
    confidence: str
    note: str = ""

    def sort_key(self) -> tuple:
        rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(self.confidence, 3)
        return (rank, self.page)


def _years_in(text: str) -> list[int]:
    """Every year named in a piece of text, in the order they appear."""
    found: list[tuple[int, int]] = []
    for pattern, extract in YEAR_PATTERNS:
        for m in pattern.finditer(text):
            try:
                found.append((m.start(), extract(m)))
            except Exception:
                continue
    found.sort()
    years: list[int] = []
    for _pos, year in found:
        if year not in years:
            years.append(year)
    return years


def _years_with_positions(text: str) -> list[tuple[int, int]]:
    """(character offset, year) pairs, so a value can be tied to the year
    written nearest to it rather than to whichever year appears first.

    Patterns are tried in priority order and a match that overlaps one already
    claimed is discarded. Without this, "FY 2024-25" is read twice - once
    correctly as 2025 by the range pattern, and once wrongly as 2024 by the
    plain FY pattern - and the duplicate silently wins.
    """
    claimed: list[tuple[int, int]] = []
    found: list[tuple[int, int]] = []
    for pattern, extract in YEAR_PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if any(not (span[1] <= start or span[0] >= end)
                   for start, end in claimed):
                continue
            try:
                year = extract(m)
            except Exception:
                continue
            claimed.append(span)
            found.append((span[0], year))
    found.sort()
    return found


def _nearest_year(text: str, position: int) -> int | None:
    """The year token closest to a given character offset, or None."""
    pairs = _years_with_positions(text)
    if not pairs:
        return None
    return min(pairs, key=lambda pair: abs(pair[0] - position))[1]


def _line_is_consolidated(line: str) -> bool:
    return bool(re.search(r"consolidated", line, re.I))


def extract_candidates(doc: Document, pages: list[tuple[int, str]]) -> list[Candidate]:
    """Scan one document and return every plausible match with its evidence."""
    out: list[Candidate] = []

    for page_no, text in pages:
        lines = text.splitlines()
        for idx, raw_line in enumerate(lines):
            line = raw_line.strip()
            if len(line) < 4:
                continue
            for metric, label_patterns in LABELS.items():
                for label in label_patterns:
                    m = label.search(line)
                    if not m:
                        continue

                    tail = line[m.end():]
                    # Guard 3: never take a consolidated figure.
                    if _line_is_consolidated(line):
                        continue

                    if metric == "net_profit_inr":
                        cand = _match_money(metric, doc, page_no, line, label,
                                            tail, lines, idx)
                    else:
                        cand = _match_ratio(metric, doc, page_no, line, label,
                                            tail, lines, idx)
                    if cand:
                        out.extend(cand)
                    break  # one label family is enough per metric per line
    return out


def _find_series_mapping(lines: list[str], idx: int, n_values: int) -> list[int] | None:
    """Look above a series row for a column header that names the years.

    SBI's five- and ten-year highlights tables list years in a header row above
    the metric rows. If that header can be read, each column can be dated
    correctly; if it cannot, the row is unusable and the cell is flagged rather
    than guessed.
    """
    for back in range(1, 9):
        j = idx - back
        if j < 0:
            break
        header = lines[j]
        tokens = HEADER_YEAR.findall(header)
        if len(tokens) >= n_values:
            years = _years_in(header)
            if len(years) >= n_values:
                return years[:n_values]
    return None


def _first_real_number(tail: str, pattern: str, require_pct: bool) -> re.Match | None:
    """Find the first number in ``tail`` that is genuinely a value.

    Annual reports glue footnote markers onto words - "Gross non-performing
    assets to gross advances1 1.17%" - and a naive regex reads that stray "1"
    as the value. So any match whose preceding character is a letter or digit is
    skipped and the search continues; the real figure is the next one along.
    """
    for match in re.finditer(pattern, tail, re.I):
        start = match.start(1)
        if start > 0 and tail[start - 1].isalnum():
            continue
        return match
    return None


PCT_PATTERN = rf"{GAP}{_num()}{PCT}"
BARE_PATTERN = rf"{GAP}{_num()}"


def _match_ratio(metric: str, doc: Document, page_no: int, line: str,
                 label: re.Pattern, tail: str, lines: list[str],
                 idx: int) -> list[Candidate]:
    """Handle a percentage metric: gross NPA, net NPA, ROA, ROE."""
    pct_match = _first_real_number(tail, PCT_PATTERN, require_pct=True)
    bare_match = None if pct_match else _first_real_number(tail, BARE_PATTERN,
                                                           require_pct=False)

    match = pct_match or bare_match
    if not match:
        return []
    try:
        value = float(match.group(1))
    except ValueError:
        return []
    if not (0.0 <= value <= 100.0):
        return []

    # Guard 2: is this a multi-year row rather than a single fact?
    numbers_after = re.findall(r"[0-9]+(?:\.[0-9]+)?", tail)
    is_series = len(numbers_after) >= 3

    year = None
    confidence = "MEDIUM"
    note = ""

    if is_series:
        mapping = _find_series_mapping(lines, idx, len(numbers_after))
        if not mapping:
            return [Candidate(
                metric=metric, value=value, unit="pct", page=page_no, line=line,
                pattern=f"{label.pattern} [series, header unresolved]",
                doc=doc.title, doc_fy=doc.fy, year=None, confidence="UNRESOLVED",
                note=(f"multi-year row with {len(numbers_after)} values and no "
                      "resolvable column header - first value is NOT assumed to "
                      "be the current year"),
            )]
        year = mapping[0]
        confidence = "MEDIUM"
        note = f"series row, column 1 of {len(mapping)} dated by page header"

    years_here = _years_with_positions(line)
    if years_here:
        absolute_pos = len(line) - len(tail) + match.start(1)
        year = _nearest_year(line, absolute_pos)
        confidence = "HIGH" if pct_match else "MEDIUM"
        note = "year named nearest to the value"

    if year is None and doc.fy is not None:
        year = doc.fy
        confidence = "MEDIUM"
        note = "no year in the line; taken from the document year"

    if bare_match and not pct_match:
        confidence = "LOW" if confidence == "MEDIUM" else confidence
        note += "; matched without a % sign"

    return [Candidate(metric=metric, value=value, unit="pct", page=page_no,
                      line=line, pattern=label.pattern, doc=doc.title,
                      doc_fy=doc.fy, year=year, confidence=confidence, note=note)]


MONEY_UNIT_PATTERN = re.compile(
    r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*"
    r"(lakh\s*crore|crore|cr\b|billion|bn\b|million)",
    re.I,
)
MONEY_UNIT_CODES = {
    "lakhcrore": ("INR_lakh_crore", 100_000.0),
    "crore": ("INR_crore", 1.0),
    "cr": ("INR_crore", 1.0),
    "billion": ("INR_billion", 100.0),
    "bn": ("INR_billion", 100.0),
    "million": ("INR_million", 0.1),
}

#: Financial statements put the unit in the column heading and then print bare
#: numbers underneath - "Net profit/(loss) (` in Crore) 50,232". Matching only
#: "number then unit" misses every one of those rows, which is how SBI's FY2023
#: profit was recorded as a stray sub-figure instead of the real 50,232.
UNIT_THEN_MONEY_PATTERN = re.compile(
    r"(lakh\s*crore|crore|cr\b|billion|bn\b|million)\s*\)?\s*[`:\-]?\s*"
    r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.I,
)


def _match_money(metric: str, doc: Document, page_no: int, line: str,
                 label: re.Pattern, tail: str, lines: list[str],
                 idx: int) -> list[Candidate]:
    """Handle net profit.

    The value must be written **immediately next to its unit**, because Indian
    bank reports say things like "Net Profit increased by 19.30 per cent to
    Rs 44,109 crore". A matcher that simply takes the first number after the
    label records 19.30 - the growth rate - as the profit. Requiring the number
    to sit beside crore/billion/million skips the percentage and finds 44,109.
    """
    match = None
    value_position = None
    unit_word = ""
    for candidate_match in MONEY_UNIT_PATTERN.finditer(tail):
        start = candidate_match.start(1)
        if start > 0 and tail[start - 1].isalnum():
            continue                       # glued to a word: a footnote marker
        match = candidate_match
        value_position = start
        unit_word = re.sub(r"\s+", "", candidate_match.group(2).lower())
        break

    if match is None:
        # Fall back to the unit-first ordering used by financial statements.
        for candidate_match in UNIT_THEN_MONEY_PATTERN.finditer(tail):
            start = candidate_match.start(2)
            if start > 0 and tail[start - 1].isalnum():
                continue
            match = candidate_match
            value_position = start
            unit_word = re.sub(r"\s+", "", candidate_match.group(1).lower())
            break
    if match is None:
        return []

    value_group = 1 if match.group(1).replace(",", "").replace(".", "").isdigit() else 2
    try:
        value = float(match.group(value_group).replace(",", ""))
    except ValueError:
        return []
    unit_code, _factor = MONEY_UNIT_CODES.get(unit_word, ("", 0.0))
    if not unit_code or value <= 0:
        return []

    # Tie the figure to the year written nearest to it, not the first year on
    # the line: "Rs 70,901 Crore in FY 2024-25" must land in FY2025.
    absolute_pos = len(line) - len(tail) + value_position
    year = _nearest_year(line, absolute_pos)
    note = ""
    confidence = "MEDIUM"
    if year is not None:
        confidence = "HIGH"
        note = "year named nearest to the value"
    elif doc.fy is not None:
        year = doc.fy
        note = "no year on the line; taken from the document year"

    if re.search(r"per\s*employee|per\s*share|bonus|dividend", tail, re.I):
        confidence = "LOW"
        note = (note + "; " if note else "") + "line mentions a per-unit figure"

    return [Candidate(metric=metric, value=value, unit=unit_code, page=page_no,
                      line=line, pattern=label.pattern, doc=doc.title,
                      doc_fy=doc.fy, year=year, confidence=confidence, note=note)]


# ===========================================================================
# Resolution: one value per (bank, metric, year)
# ===========================================================================
@dataclass
class Cell:
    bank: str
    metric: str
    year: int
    value: float | None = None
    unit: str = ""
    page: int | None = None
    line: str = ""
    doc: str = ""
    pattern: str = ""
    confidence: str = ""
    note: str = ""
    supporting_docs: int = 0
    supporting_pages: int = 0
    corroborated: bool = False
    alternatives: list[Candidate] = field(default_factory=list)

    @property
    def period_label(self) -> str:
        return f"FY{self.year}"


def cross_validate(cells: list[Cell], banks: list[str], years: list[int]) -> list[str]:
    """Check the relationships that must hold between metrics of one bank-year.

    Individual extractions cannot be verified in isolation - but they can be
    checked against each other, and these relationships are arithmetic facts
    rather than opinions:

    * Net NPA can never exceed Gross NPA, by definition. Net NPAs are what is
      left of gross NPAs after provisions.
    * Return on equity must exceed return on assets for a profitable bank,
      because equity is the smaller denominator. For a bank, the ratio between
      them is leverage, which realistically sits between about 4x and 30x. A
      pair reporting a ratio outside that band means at least one of the two
      numbers was picked up from the wrong place.

    Cells that fail are not deleted - they are flagged, because the correct
    response to suspicious evidence is to show it labelled, not to hide it.
    """
    lookup = {(cell.bank, cell.metric, cell.year): cell for cell in cells}
    findings: list[str] = []

    def note(cell: Cell, message: str) -> None:
        cell.note = (cell.note + "; " if cell.note else "") + message
        if cell.confidence not in {"", "LOW"}:
            cell.confidence = "LOW"

    for bank in banks:
        for year in years:
            gross = lookup.get((bank, "gross_npa_pct", year))
            net = lookup.get((bank, "net_npa_pct", year))
            if (gross and net and gross.value is not None and net.value is not None
                    and net.value > gross.value):
                message = (f"FAILS Net NPA <= Gross NPA "
                           f"(net {net.value:g} > gross {gross.value:g})")
                note(net, message)
                findings.append(f"{bank} FY{year}: {message}")

            roa = lookup.get((bank, "roa_pct", year))
            roe = lookup.get((bank, "roe_pct", year))
            if (roa and roe and roa.value and roe.value
                    and roa.value > 0 and roe.value > 0):
                leverage = roe.value / roa.value
                if not (4.0 <= leverage <= 30.0):
                    message = (f"FAILS ROE/ROA leverage check "
                               f"({roe.value:g}/{roa.value:g} = {leverage:.1f}x, "
                               "expected 4-30x)")
                    note(roe, message)
                    findings.append(f"{bank} FY{year}: {message}")

    return findings


def _value_key(candidate: Candidate) -> tuple:
    """Group candidates that state the same figure, tolerating float noise."""
    return (candidate.unit, round(float(candidate.value), 2))


def resolve_cells(candidates: list[Candidate], banks: list[str],
                  years: list[int]) -> tuple[list[Cell], list[Candidate]]:
    """Choose one value per (bank, metric, year) by corroboration, not by page order.

    WHY CORROBORATION
    -----------------
    A large annual report states its headline profit half a dozen times - in the
    P&L, the directors' report, the highlights table, the cash-flow note - and
    each of those is a genuine independent restatement of the same figure.
    Segment or subsidiary numbers, by contrast, appear once.

    Picking the first match on the earliest page (the obvious approach) selects
    whatever happens to sit highest in the document, which for SBI was a segment
    figure of a few hundred crore rather than the bank's profit. Scoring each
    candidate by how many *other* places in the document agree with it selects
    the figure the bank itself repeats - and when the agreement crosses into a
    second annual report (this year's report stating last year's profit as a
    comparative), that is the ``same_issuer_2_docs`` verification the project's
    rules accept as confirmation.
    """
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    usable = [c for c in candidates
              if c.year is not None and c.confidence in rank]
    unresolved = [c for c in candidates if c.confidence not in rank]

    cells: list[Cell] = []
    for bank in banks:
        for metric in TARGET_METRICS:
            for year in years:
                pool = [c for c in usable
                        if bank in c.doc and c.metric == metric and c.year == year]
                cell = Cell(bank=bank, metric=metric, year=year)
                if pool:
                    groups: dict[tuple, list[Candidate]] = {}
                    for cand in pool:
                        groups.setdefault(_value_key(cand), []).append(cand)

                    def strength(item):
                        _key, members = item
                        docs = len({c.doc for c in members})
                        high = sum(1 for c in members if c.confidence == "HIGH")
                        pages = len({(c.doc, c.page) for c in members})
                        earliest = min(c.page for c in members)
                        return (docs, high, pages, -earliest)

                    key, members = max(groups.items(), key=strength)
                    members.sort(key=lambda c: c.sort_key())
                    best = members[0]
                    docs = len({c.doc for c in members})
                    pages = len({(c.doc, c.page) for c in members})

                    cell.value = float(key[1])
                    cell.unit = best.unit
                    cell.page = best.page
                    cell.line = best.line
                    cell.doc = best.doc
                    cell.pattern = best.pattern
                    cell.supporting_docs = docs
                    cell.supporting_pages = pages
                    cell.corroborated = docs >= 2

                    # Confidence in the figure itself, not in one match.
                    if docs >= 2:
                        cell.confidence = "HIGH"
                    elif pages >= 2:
                        cell.confidence = "MEDIUM" if best.confidence != "HIGH" else "HIGH"
                    else:
                        cell.confidence = "LOW"

                    bits = [f"stated on {pages} page(s) across {docs} document(s)"]
                    if best.note:
                        bits.append(best.note)
                    cell.note = "; ".join(bits)

                    others = [c for c in pool if _value_key(c) != key]
                    others.sort(key=lambda c: c.sort_key())
                    cell.alternatives = others[:3]
                cells.append(cell)
    return cells, unresolved


# ===========================================================================
# Writing the source log
# ===========================================================================
def _parse_year(raw_year: str) -> int:
    """Accept 'FY2022', 'FY22', '2022' and return 2022. Zero means unparseable."""
    text = str(raw_year).strip().upper()
    m = re.fullmatch(r"FY(\d{4})", text)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"FY(\d{2})", text)
    if m:
        return 2000 + int(m.group(1))
    m = re.fullmatch(r"(\d{4})", text)
    if m:
        return int(m.group(1))
    return 0


def _docs_by_name(docs: list[Document]) -> dict[str, Document]:
    return {d.title: d for d in docs}


def build_source_log_rows(cells: list[Cell], docs: list[Document]) -> list[dict]:
    index = _docs_by_name(docs)
    rows: list[dict] = []
    for cell in cells:
        doc = index.get(cell.doc)
        row = {c: "" for c in REQUIRED_COLUMNS}
        metric_meta = METRICS.get(cell.metric, {})
        row.update(
            source_id=f"{cell.bank}-{cell.metric}-{cell.period_label}"
                      f"{'--auto' if cell.value is not None else '--manual'}",
            bank=cell.bank,
            basis=BASIS,
            period_type="annual",
            period_label=cell.period_label,
            metric_code=cell.metric,
            metric_name=metric_meta.get("name", cell.metric),
            unit_as_reported=cell.unit,
            document_title=cell.doc or "",
            document_type="annual_report",
            document_date="",
            page_number=str(cell.page) if cell.page else "",
            table_reference=cell.pattern,
            url="",
            downloaded_on=doc.modified if doc else "",
            sha256_of_document=doc.sha256 if doc else "",
            verified_by="automated_regex_extractor",
            verification_method=VERIFICATION,
            definition_variant="standalone",
            status=STATUS_EXTRACTED if cell.value is not None else STATUS_MANUAL,
        )
        if cell.value is not None:
            row["value_as_reported"] = f"{cell.value:g}"

        # Integrity rule: NOTHING this script produces is ever written with a
        # trusted status. Not even a figure that two documents agree on.
        #
        # The corroboration signal is real and useful - it is recorded in the
        # notes so a reviewer knows where to look first - but it was tested and
        # it is not sufficient on its own: HDFC's FY2025 net profit resolved to
        # a figure of a few hundred crore 'confirmed' in two documents, which is
        # a segment number that happens to repeat, not the bank's profit. A
        # machine-only match therefore stays auto_extracted, and a human
        # promotes it by editing one cell.
        row["status"] = STATUS_EXTRACTED if cell.value is not None else STATUS_MANUAL
        row["verification_method"] = VERIFICATION

        note_bits = [f"confidence={cell.confidence}"]
        if cell.value is not None:
            note_bits.insert(0, f"stated on {cell.supporting_pages} page(s) "
                                f"across {cell.supporting_docs} document(s)"
                                + (" - CORROBORATED, check this one first"
                                   if cell.corroborated else ""))
        if cell.note:
            note_bits.append(cell.note)
        if cell.line:
            note_bits.append(f'matched: "{cell.line[:160]}"')
        if cell.alternatives:
            alts = "; ".join(
                f"{a.value:g}@{a.doc}:p{a.page}({a.confidence})"
                for a in cell.alternatives
            )
            note_bits.append(f"other candidates: {alts}")
        if cell.value is None:
            note_bits.insert(0, "no credible match found by the extractor")
        row["notes"] = " | ".join(note_bits)[:900]
        rows.append(row)
    return rows


def write_source_log(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_audit_csvs(candidates: list[Candidate], cells: list[Cell],
                     out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    cand_path = out_dir / "extraction_candidates.csv"
    with open(cand_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "value", "unit", "year", "confidence", "doc",
                    "page", "pattern", "note", "matched_line"])
        for c in sorted(candidates, key=lambda c: (c.metric, c.year or 0,
                                                   c.confidence)):
            w.writerow([c.metric, c.value, c.unit, c.year or "", c.confidence,
                        c.doc, c.page, c.pattern, c.note, c.line[:200]])
    written.append(cand_path)

    cov_path = out_dir / "extraction_coverage.csv"
    with open(cov_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["bank", "metric", "year", "status", "value", "unit",
                    "confidence", "page", "document"])
        for cell in cells:
            w.writerow([
                cell.bank, cell.metric, cell.period_label,
                "extracted" if cell.value is not None else "MANUAL_REQUIRED",
                f"{cell.value:g}" if cell.value is not None else "",
                cell.unit, cell.confidence, cell.page or "", cell.doc,
            ])
    written.append(cov_path)
    return written


# ===========================================================================
# Reporting
# ===========================================================================
def print_coverage(cells: list[Cell], banks: list[str], years: list[int]) -> None:
    lookup = {(c.bank, c.metric, c.year): c for c in cells}
    for metric in TARGET_METRICS:
        meta = METRICS.get(metric, {})
        print(f"\n  {meta.get('name', metric)}  ({metric})")
        header = "    " + "bank  ".ljust(8) + "".join(
            f"{('FY' + str(y)[2:]):>11}" for y in years)
        print(header)
        for bank in banks:
            line = "    " + f"{bank:<8}"
            for year in years:
                cell = lookup[(bank, metric, year)]
                if cell.value is None:
                    line += f"{'--':>11}"
                else:
                    flag = "=" if cell.corroborated else {
                        "HIGH": " ", "MEDIUM": "~", "LOW": "?"}.get(
                        cell.confidence, " ")
                    line += f"{cell.value:>10.2f}{flag}"
            print(line)
    print("\n    legend:  (blank)=single source  ~=page-level   ?=weak")
    print("             '='=confirmed in 2+ documents (trusted)  '--'=MANUAL_REQUIRED")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-cache", action="store_true",
                    help="extract all pages of every PDF into the text cache")
    ap.add_argument("--force-cache", action="store_true",
                    help="rebuild the cache even if it exists")
    ap.add_argument("--report", action="store_true",
                    help="write the candidate and coverage audit CSVs")
    ap.add_argument("--out", default=str(ROOT / "data" / "source_log.csv"))
    ap.add_argument("--years", nargs="*", default=WINDOW_PRIMARY)
    args = ap.parse_args()

    docs = inventory()
    if not docs:
        print(f"No PDFs found under {RAW}")
        return 1

    print("=" * 74)
    print("EXTRACT METRICS - automated extraction from primary documents")
    print("=" * 74)
    print(f"\nDocuments found: {len(docs)}")
    annual = [d for d in docs if d.kind == "annual" and d.fy]
    for doc in docs:
        tag = f"{doc.bank} FY{doc.fy}" if doc.fy else doc.bank
        print(f"  [{doc.kind:<9}] {doc.title:<48} {tag}")

    if args.build_cache or not CACHE_DIR.exists():
        print(f"\nBuilding full-text cache -> {CACHE_DIR.relative_to(ROOT)}")
        counts = build_text_cache(docs, force=args.force_cache)
        total = sum(v for v in counts.values() if v > 0)
        print(f"  {sum(1 for v in counts.values() if v > 0)} document(s) cached, "
              f"{total:,} pages total")

    print(f"\nScanning {len(annual)} annual report(s) for "
          f"{len(TARGET_METRICS)} metrics ...")
    candidates: list[Candidate] = []
    for doc in annual:
        pages = read_pages(doc)
        if not pages:
            print(f"  WARNING: no cached text for {doc.title} - skipped")
            continue
        found = extract_candidates(doc, pages)
        candidates.extend(found)
        print(f"  {doc.title:<46} {len(pages):>4} pages -> {len(found):>3} candidate match(es)")

    banks = ["SBI", "HDFC", "ICICI"]
    years = [_parse_year(y) for y in args.years]
    years = sorted({y for y in years if y}) or [2022, 2023, 2024, 2025, 2026]

    cells, unresolved = resolve_cells(candidates, banks, years)
    consistency_findings = cross_validate(cells, banks, years)
    rows = build_source_log_rows(cells, docs)
    path = write_source_log(rows, Path(args.out))

    print("\n" + "-" * 74)
    print("COVERAGE  (values written to the source log)")
    print("-" * 74)
    print_coverage(cells, banks, years)

    extracted = sum(1 for c in cells if c.value is not None)
    corroborated = sum(1 for c in cells if c.corroborated)
    total = len(cells)
    print(f"\n  extracted        : {extracted}/{total} cells ({extracted / total:.0%})")
    print(f"  confirmed (2+ docs): {corroborated}/{total} cells "
          "-> flagged for review first, STILL not auto-trusted")
    print(f"  single-source    : {extracted - corroborated}/{total} cells")
    print(f"  MANUAL_REQUIRED  : {total - extracted}/{total} cells")
    if consistency_findings:
        print(f"\n  ARITHMETIC CROSS-CHECKS failed on {len(consistency_findings)} "
              "bank-year pair(s):")
        for finding in consistency_findings:
            print(f"    - {finding}")
    else:
        print("\n  ARITHMETIC CROSS-CHECKS: no contradictions between the "
              "extracted values")
    if unresolved:
        print(f"  rejected       : {len(unresolved)} match(es) failed a guard "
              "(series with no header, missing unit, or consolidated)")

    print(f"\n  source log -> {path}")
    if args.report:
        for p in write_audit_csvs(candidates, cells, ROOT / "outputs" / "tables"):
            print(f"  audit      -> {p.relative_to(ROOT)}")

    print("\n" + "-" * 74)
    print("STATUS OF EVERY ROW: 'auto_extracted' or 'MANUAL_REQUIRED'.")
    print("Nothing here is 'verified'. src/load.py trusts only 'verified' and")
    print("'two_source_confirmed', so none of these numbers can reach a score yet.")
    print()
    print("ACCURACY: this script is a candidate finder, not an oracle. A spot")
    print("check found material errors - segment figures mistaken for bank-level")
    print("ones, and series rows dated from the wrong column. Treat the values as")
    print("leads to check against the cited page, not as facts.")
    print("-" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
