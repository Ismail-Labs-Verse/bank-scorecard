"""pdf_probe.py - the honest answer to "can we read the bank PDFs automatically?"

This module does NOT put any number into the verified dataset. It only reports
what is mechanically extractable, so a human can decide what to do next.

For every PDF in data/raw/ it records:
  * pages, and whether the page carries real text or is a scanned image
  * how many tables pdfplumber can detect
  * which known metric labels appear anywhere in the text
That is enough to answer: is automated extraction viable for this document, or
does it need a manual CSV fallback?

A scanned PDF (image-only) is a hard stop for text extraction and must be read by
a human. Saying so is the point of this file.
"""
from __future__ import annotations
import pandas as pd
from src.config import RAW, OUT_TABLES, METRICS

LABELS = {
    "gross_npa_pct": ["Gross NPA", "Gross Non-Performing", "GNPA"],
    "net_npa_pct": ["Net NPA", "Net Non-Performing", "NNPA"],
    "pcr_pct": ["Provision Coverage", "PCR"],
    "slippage_pct": ["Slippage", "Fresh Slippage"],
    "credit_cost_pct": ["Credit Cost", "Credit cost"],
    "nim_pct": ["Net Interest Margin", "NIM"],
    "roa_pct": ["Return on Asset", "ROA"],
    "roe_pct": ["Return on Equit", "ROE"],
    "cost_to_income_pct": ["Cost to Income", "Cost-to-Income", "Cost/Income"],
    "crar_pct": ["Capital Adequacy", "CRAR"],
    "cet1_pct": ["CET1", "CET-1", "Common Equity Tier"],
    "net_profit_inr": ["Net Profit", "Profit After Tax", "PAT"],
    "nii_inr": ["Net Interest Income"],
    "deposits_inr": ["Deposits"],
    "advances_inr": ["Advances"],
}


def probe_file(path, max_pages=25):
    import pdfplumber
    rec = dict(file=str(path.relative_to(RAW)), pages=None, pages_probed=0,
               text_chars=0, pages_with_text=0, looks_scanned=False,
               tables_found=0, labels_found="", error="")
    try:
        with pdfplumber.open(path) as pdf:
            rec["pages"] = len(pdf.pages)
            n = min(len(pdf.pages), max_pages)
            rec["pages_probed"] = n
            found, tables = set(), 0
            text_total = 0
            pages_with_text = 0
            for page in pdf.pages[:n]:
                t = page.extract_text() or ""
                text_total += len(t)
                if len(t.strip()) > 40:
                    pages_with_text += 1
                for code, needles in LABELS.items():
                    if any(nd.lower() in t.lower() for nd in needles):
                        found.add(code)
                try:
                    tables += len(page.find_tables() or [])
                except Exception:
                    pass
            rec.update(text_chars=text_total, pages_with_text=pages_with_text,
                       tables_found=tables, looks_scanned=(pages_with_text == 0),
                       labels_found=";".join(sorted(found)))
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def probe_all():
    files = sorted(RAW.rglob("*.pdf")) if RAW.exists() else []
    rows = [probe_file(p) for p in files]
    df = pd.DataFrame(rows)
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    if not df.empty:
        df.to_csv(OUT_TABLES / "pdf_probe_report.csv", index=False)
    else:
        pd.DataFrame(columns=["file", "pages", "pages_probed", "text_chars",
                              "pages_with_text", "looks_scanned", "tables_found",
                              "labels_found", "error"]).to_csv(
            OUT_TABLES / "pdf_probe_report.csv", index=False)
    return df
