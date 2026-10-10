"""load.py - turns the human-verified source log into the analysis table.

THE ONE RULE THIS MODULE OBEYS: it never invents a value.
It reads data/source_log.csv (one row per number, filled by a human from primary
documents), normalises units, and writes data/processed/master_long.csv.
If the source log is missing or empty it raises SourceLogMissing so the whole
pipeline stops with a clear message instead of quietly producing a guess.

A row with an EMPTY value and status UNVERIFIED is valid and meaningful: it says
"we looked for this number and could not verify it". A blank is better than a guess.
"""
from __future__ import annotations
import pandas as pd
from src.config import (SOURCE_LOG, PROCESSED, ACCEPTED_UNITS, UNIT_TO_CRORE,
                        METRICS, BASIS, TRUSTED_STATUSES)


class SourceLogMissing(Exception):
    """Raised when the pipeline has nothing verified to work with."""


REQUIRED_COLUMNS = [
    "source_id", "bank", "basis", "period_type", "period_label",
    "metric_code", "metric_name", "value_as_reported", "unit_as_reported",
    "document_title", "document_type", "document_date", "page_number",
    "table_reference", "url", "downloaded_on", "sha256_of_document",
    "verified_by", "verification_method", "definition_variant", "status", "notes",
]

# Statuses the pipeline understands.
#   verified / two_source_confirmed -> trusted, may enter the scorecard
#   auto_extracted                  -> found by src/extract_metrics.py, NOT yet
#                                      checked by a human, so never trusted
#   ocr_extracted                   -> read from chart coordinates on a
#                                      highlights page by
#                                      src/extract_icici_ocr.py; also not
#                                      trusted until reviewed
#   MANUAL_REQUIRED                 -> the extractor looked and found nothing
#                                      credible; a human must supply it
#   conflict / UNVERIFIED           -> declared but unresolved / not checked
VALID_STATUS = {"verified", "two_source_confirmed", "conflict", "UNVERIFIED",
                "auto_extracted", "ocr_extracted", "MANUAL_REQUIRED"}
VALID_PERIOD_TYPES = {"annual", "quarter"}
VALID_VERIFICATION = {"recomputed", "cross_issuer", "same_issuer_2_docs", "single_source", ""}


def read_source_log(path=None) -> pd.DataFrame:
    path = SOURCE_LOG if path is None else path
    if not path.exists():
        raise SourceLogMissing(
            f"No source log at {path}.\n"
            "The pipeline cannot compute anything yet, because nothing has been "
            "verified against a primary document.\n"
            "Next step: copy data/source_log_TEMPLATE.csv to data/source_log.csv and "
            "fill one row per number, with the document name and page number."
        )
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if df.empty:
        raise SourceLogMissing(
            f"{path} exists but contains no rows (header only).\n"
            "Nothing is verified yet, so there is nothing to compute."
        )
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SourceLogMissing(
            f"{path} is missing required columns: {missing}\n"
            "Compare it against data/source_log_TEMPLATE.csv."
        )
    return df


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Clean types, convert units to the two canonical units, flag score eligibility."""
    out = df.copy()
    for col in ["bank", "basis", "period_type", "period_label", "metric_code",
                "unit_as_reported", "status", "verification_method",
                "definition_variant", "source_id"]:
        out[col] = out[col].astype(str).str.strip()

    # An empty value string means "declared but not verified" -> NaN, never 0.
    out["value_as_reported"] = pd.to_numeric(
        out["value_as_reported"].replace("", None), errors="coerce")

    unknown = sorted(set(out["unit_as_reported"]) - set(ACCEPTED_UNITS) - {""})
    if unknown:
        raise ValueError(f"Unknown unit(s) in source log: {unknown}. "
                         f"Accepted: {ACCEPTED_UNITS}")

    # --- unit conversion, applied only to non-empty values ---
    def convert(row):
        v, u = row["value_as_reported"], row["unit_as_reported"]
        if pd.isna(v) or u == "":
            return pd.Series([None, ""])
        if u == "pct":
            return pd.Series([float(v), "pct"])
        if u == "ratio":
            return pd.Series([float(v) * 100.0, "pct"])   # 0.18 -> 18%
        return pd.Series([float(v) * UNIT_TO_CRORE[u], "INR_crore"])

    out[["value_normalised", "unit_normalised"]] = out.apply(convert, axis=1)

    out = out[out["basis"] == BASIS].copy()          # standalone only, by design
    out["is_annual"] = out["period_type"] == "annual"
    out["is_snapshot"] = out["period_type"] == "quarter"
    out["is_scored_metric"] = out["metric_code"].isin(METRICS) & out["metric_code"].map(
        lambda m: METRICS.get(m, {}).get("pillar") is not None)
    out["is_trusted"] = out["status"].isin(TRUSTED_STATUSES)
    out["has_value"] = out["value_normalised"].notna()
    # A row may enter the scorecard ONLY if it is an annual, trusted, scored
    # metric with a real value. Everything else is context.
    out["score_eligible"] = (out["is_annual"] & out["is_scored_metric"]
                             & out["is_trusted"] & out["has_value"])
    return out


def build_master_long(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return the analysis table and write it to data/processed/master_long.csv."""
    raw = read_source_log() if df is None else df
    out = normalise(raw)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    cols = ["source_id", "bank", "basis", "period_type", "period_label",
            "metric_code", "metric_name", "value_as_reported", "unit_as_reported",
            "value_normalised", "unit_normalised", "is_annual", "is_snapshot",
            "is_scored_metric", "is_trusted", "has_value", "score_eligible",
            "status", "verification_method", "definition_variant",
            "document_title", "page_number", "url"]
    out[cols].to_csv(PROCESSED / "master_long.csv", index=False)
    return out


def coverage_report(df: pd.DataFrame) -> pd.DataFrame:
    """What do we actually have, and what is missing? One row per bank+metric."""
    rows = []
    for bank in sorted(df["bank"].unique()):
        for code in sorted(df["metric_code"].unique()):
            sub = df[(df["bank"] == bank) & (df["metric_code"] == code)]
            annual = sub[sub["is_annual"]]
            rows.append(dict(
                bank=bank, metric_code=code,
                metric_name=METRICS.get(code, {}).get("name", code),
                rows=len(sub),
                annual_years=annual["period_label"].nunique(),
                with_value=int(sub["has_value"].sum()),
                unverified=int((sub["status"] == "UNVERIFIED").sum()),
                score_eligible=int(sub["score_eligible"].sum()),
                sources=sub["document_title"].nunique(),
            ))
    return pd.DataFrame(rows)


# ===========================================================================
# RAW PDF SCANNING
#
# What this is for: showing you what is mechanically readable inside the PDFs
# you drop into data/raw/, so a human can decide what to do next.
#
# What this is NOT: a data source for the scorecard. Nothing this function
# extracts is allowed into master_long.csv or into any score. Extracted text is
# dumped to data/processed/_extracted_raw/ as CANDIDATE material. Only a human
# reading the document can promote a number into data/source_log.csv, and only
# then does it become verifiable data.
#
# It never raises when there is nothing to scan. A missing folder is a warning,
# not a crash.
# ===========================================================================
import hashlib
from src.config import RAW, ROOT

EXTRACT_DIR = PROCESSED / "_extracted_raw"
MAX_PAGES_PER_PDF = 40
MAX_TABLE_ROWS_PER_PDF = 4000
BANK_FOLDER_MAP = {"hdfc": "HDFC", "sbi": "SBI", "icici": "ICICI", "rbi": "RBI"}

MANIFEST_COLUMNS = ["bank", "file", "rel_path", "sha256", "bytes", "pages",
                    "pages_probed", "text_chars", "pages_with_text",
                    "looks_scanned", "tables_found", "status", "text_dump",
                    "tables_dump", "note"]


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _bank_from_path(path, root) -> str:
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        return "unfiled"
    for part in parts:
        hit = BANK_FOLDER_MAP.get(part.lower())
        if hit:
            return hit
    return "unfiled"


def scan_raw_pdfs(verbose=True, save_text=True, extract_tables=True):
    """Scan data/raw/ for PDFs and report what can be extracted from each one.

    Returns a DataFrame manifest (one row per PDF). Returns an EMPTY manifest with
    a clear warning if there are no PDFs - it does not raise.
    """
    import pdfplumber

    if not RAW.exists():
        if verbose:
            print(f"WARNING: {RAW} does not exist. Nothing to scan.")
            print("         Create data/raw/hdfc/, data/raw/sbi/, data/raw/rbi/ "
                  "and put the downloaded PDFs there.")
        return pd.DataFrame(columns=MANIFEST_COLUMNS)

    pdfs = sorted(RAW.rglob("*.pdf"))
    if not pdfs:
        if verbose:
            print(f"WARNING: no PDF files found under {RAW}.")
            print("         Expected folders: data/raw/hdfc/, data/raw/sbi/, data/raw/rbi/")
            print("         See data/raw/MANUAL_DOWNLOAD_NEEDED.txt for the list.")
            print("         Continuing without raw documents - the pipeline can still run,")
            print("         but it will have nothing to verify numbers against.")
        return pd.DataFrame(columns=MANIFEST_COLUMNS)

    if verbose:
        print(f"Found {len(pdfs)} PDF(s) under {RAW}")

    rows = []
    for path in pdfs:
        bank = _bank_from_path(path, RAW)
        rec = {c: "" for c in MANIFEST_COLUMNS}
        rec.update(bank=bank, file=path.name,
                   rel_path=str(path.relative_to(RAW)),
                   bytes=path.stat().st_size, status="ok")
        try:
            rec["sha256"] = _sha256(path)
        except Exception as exc:
            rec.update(status="unreadable", note=f"hash failed: {exc}")
            rows.append(rec)
            continue

        try:
            with pdfplumber.open(path) as pdf:
                rec["pages"] = len(pdf.pages)
                n = min(len(pdf.pages), MAX_PAGES_PER_PDF)
                rec["pages_probed"] = n
                chunks, table_rows, tables_found, text_chars, pages_with_text = [], [], 0, 0, 0
                for pno, page in enumerate(pdf.pages[:n], start=1):
                    try:
                        t = page.extract_text() or ""
                    except Exception:
                        t = ""
                    if len(t.strip()) > 40:
                        pages_with_text += 1
                    text_chars += len(t)
                    chunks.append(f"\n\n===== page {pno} =====\n{t}")
                    if extract_tables and len(table_rows) < MAX_TABLE_ROWS_PER_PDF:
                        try:
                            for ti, tbl in enumerate(page.extract_tables() or []):
                                tables_found += 1
                                for ri, trow in enumerate(tbl or []):
                                    if len(table_rows) >= MAX_TABLE_ROWS_PER_PDF:
                                        break
                                    for ci, cell in enumerate(trow or []):
                                        if len(table_rows) >= MAX_TABLE_ROWS_PER_PDF:
                                            break
                                        table_rows.append(dict(
                                            page=pno, table=ti, row=ri, col=ci,
                                            value="" if cell is None else str(cell)))
                        except Exception:
                            pass
                rec.update(text_chars=text_chars, pages_with_text=pages_with_text,
                           tables_found=tables_found,
                           looks_scanned=(pages_with_text == 0))
                if rec["looks_scanned"]:
                    rec["status"] = "scanned_image"
                    rec["note"] = ("no embedded text on the first "
                                   f"{n} page(s): this PDF is a scan and needs OCR or "
                                   "a human to read it")
                if save_text:
                    d = EXTRACT_DIR / bank
                    d.mkdir(parents=True, exist_ok=True)
                    stem = path.stem[:80]
                    tp = d / f"{stem}.txt"
                    tp.write_text("".join(chunks), encoding="utf-8")
                    rec["text_dump"] = str(tp.relative_to(ROOT))
                    if table_rows:
                        tbp = d / f"{stem}_tables.csv"
                        pd.DataFrame(table_rows).to_csv(tbp, index=False)
                        rec["tables_dump"] = str(tbp.relative_to(ROOT))
        except Exception as exc:
            rec.update(status="unreadable", note=f"{type(exc).__name__}: {exc}")
        rows.append(rec)

    df = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    if verbose:
        print(df[["bank", "file", "pages", "text_chars", "tables_found", "status"]]
              .to_string(index=False))
        scanned = df[df.status == "scanned_image"]
        if not scanned.empty:
            print(f"\nNEEDS A HUMAN: {len(scanned)} PDF(s) are image-only scans and "
                  "cannot be read by text extraction.")
    return df


def write_scan_manifest(df=None):
    """Save the scan manifest next to the extracted text."""
    if df is None:
        df = scan_raw_pdfs(verbose=False)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    p = PROCESSED / "raw_pdf_manifest.csv"
    df.to_csv(p, index=False)
    return p
