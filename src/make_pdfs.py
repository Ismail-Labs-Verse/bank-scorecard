"""Build the two written deliverables as PDFs.

Outputs
-------
``docs/understanding_guide.pdf``
    A plain-English companion: what each metric means, how to read every chart,
    what a score does and does not say, and a set of interview questions with
    worked answers.

``docs/case_study_memo.pdf``
    A two-page research note in the shape an analyst would circulate: the
    question, the method, what the evidence currently supports, the risk
    register and the document appendix.

Reproducibility
---------------
The build date is taken from ``SOURCE_DATE_EPOCH`` when that environment
variable is set, so a rebuild produces the same document instead of one stamped
with whatever day it happened to run.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Image, KeepTogether, PageBreak,
                                Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import OUT_CHARTS, OUT_TABLES, SOURCE_LOG, WINDOW_PRIMARY

DOCS = ROOT / "docs"

# ---------------------------------------------------------------------------
# Design tokens - identical to the chart palette so the pack reads as one piece
# ---------------------------------------------------------------------------
NAVY = colors.HexColor("#1B2A4A")
GOLD = colors.HexColor("#D4AF37")
SLATE = colors.HexColor("#6B7A8F")
LIGHT = colors.HexColor("#F5F5F5")
RULE = colors.HexColor("#D8DCE2")
BODY = colors.HexColor("#22282F")

BANK_COLOR = {"SBI": NAVY, "HDFC": GOLD, "ICICI": SLATE}


def _build_date() -> str:
    """A stable build date, honouring SOURCE_DATE_EPOCH for reproducible builds."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%d %B %Y")
    return date.today().strftime("%d %B %Y")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=20, leading=24, textColor=NAVY,
                                alignment=TA_LEFT, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"],
                                   fontName="Helvetica", fontSize=10.5, leading=14,
                                   textColor=SLATE, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold",
                             fontSize=12.5, leading=16, textColor=NAVY,
                             spaceBefore=12, spaceAfter=5),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="Helvetica-Bold",
                             fontSize=10.5, leading=14, textColor=NAVY,
                             spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica",
                               fontSize=9.6, leading=13.6, textColor=BODY,
                               alignment=TA_JUSTIFY, spaceAfter=6),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica",
                                fontSize=8.2, leading=11.4, textColor=SLATE,
                                alignment=TA_LEFT, spaceAfter=4),
        "bullet": ParagraphStyle("bullet", parent=base["BodyText"], fontName="Helvetica",
                                 fontSize=9.6, leading=13.6, textColor=BODY,
                                 leftIndent=12, bulletIndent=2, spaceAfter=3),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontName="Helvetica",
                               fontSize=8.2, leading=11, textColor=BODY),
        "cellbold": ParagraphStyle("cellbold", parent=base["Normal"],
                                   fontName="Helvetica-Bold", fontSize=8.2, leading=11,
                                   textColor=NAVY),
    }


def _table(rows, widths, styles, header: bool = True) -> Table:
    """A consistently styled table: navy header rule, hairline body rules."""
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY),
        ]
    table.setStyle(TableStyle(commands))
    return table


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------
METRIC_GLOSSARY = [
    ("Gross NPA %",
     "The share of the loan book that has stopped paying.",
     "Gross NPAs / gross advances x 100",
     "Lower is better",
     "The denominator is gross advances, not total assets. Foreign-office "
     "advances are sometimes excluded."),
    ("Net NPA %",
     "Bad loans still exposed after money has been set aside for them.",
     "Net NPAs / net advances x 100",
     "Lower is better",
     "Net NPAs = gross NPAs minus the provisions held against them."),
    ("Provision coverage ratio",
     "How much of the bad loan pile is already provided for.",
     "Provisions on NPAs / gross NPAs x 100",
     "Higher is better",
     "Banks differ on whether technical write-offs sit in the numerator, which "
     "alone can push the ratio above 100%."),
    ("Slippage ratio",
     "How fast good loans are turning bad.",
     "Fresh NPAs in the period / standard advances at the start x 100",
     "Lower is better",
     "Rarely disclosed directly; often only in an investor presentation."),
    ("Credit cost",
     "What bad loans cost the bank during the period.",
     "Provisions and write-offs / average advances x 100",
     "Lower is better",
     "Both the denominator and the treatment of write-offs vary by bank."),
    ("Net interest margin",
     "How profitable the loan book is per rupee of earning assets.",
     "Net interest income / average earning assets x 100",
     "Higher is better",
     "The denominator differs between banks: average working funds versus "
     "average earning assets."),
    ("Return on assets",
     "Profit per rupee of assets.",
     "Net profit / average total assets x 100",
     "Higher is better",
     "Some banks use period-end assets rather than an average."),
    ("Return on equity",
     "Profit per rupee of shareholders' money.",
     "Net profit / average equity x 100",
     "Higher is better",
     "Depends heavily on leverage, which is why it is decomposed."),
    ("Cost-to-income ratio",
     "The cost of running the bank per rupee of income.",
     "Operating expenses / (net interest income + other income) x 100",
     "Lower is better",
     "HDFC Bank reports a core version of this ratio; if the others do not, "
     "the numbers are not directly comparable."),
    ("CRAR / CET1",
     "Capital held against risk-weighted assets, and its highest-quality part.",
     "Total capital (or CET1) / risk-weighted assets x 100",
     "Higher is better",
     "Check whether the figure is bank-level or group-level."),
]


def _understanding_guide(styles) -> list:
    """Flowables for the plain-English companion document."""
    story: list = []
    story.append(Paragraph("Understanding the Bank Scorecard", styles["title"]))
    story.append(Paragraph(
        f"A plain-English companion to the SBI / HDFC Bank / ICICI Bank study "
        f"&nbsp;|&nbsp; built {_build_date()}", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1.4, color=GOLD, spaceAfter=10))

    story.append(Paragraph("What this study is trying to answer", styles["h2"]))
    story.append(Paragraph(
        "Three banks, five financial years, one question: which of them is the "
        "strongest, and does the answer survive a reasonable disagreement about "
        "how much each aspect of performance should count?", styles["body"]))
    story.append(Paragraph(
        "Most comparisons of this kind pick a set of weights, add up the scores "
        "and declare a winner. The weakness is that the weights are one person's "
        "judgement. This study does the same scoring, then re-draws the weights "
        "ten thousand times to measure how often the answer changes. If the "
        "ranking is stable, that is a result. If it flips easily, that is also a "
        "result, and a more honest one than a single number.", styles["body"]))

    story.append(Paragraph("The metrics, in plain English", styles["h2"]))
    rows = [[Paragraph("<b>Metric</b>", styles["cell"]),
             Paragraph("<b>What it means</b>", styles["cell"]),
             Paragraph("<b>Formula</b>", styles["cell"]),
             Paragraph("<b>Good</b>", styles["cell"]),
             Paragraph("<b>The trap</b>", styles["cell"])]]
    for name, meaning, formula, direction, trap in METRIC_GLOSSARY:
        rows.append([Paragraph(f"<b>{name}</b>", styles["cellbold"]),
                     Paragraph(meaning, styles["cell"]),
                     Paragraph(formula, styles["cell"]),
                     Paragraph(direction, styles["cell"]),
                     Paragraph(trap, styles["cell"])])
    story.append(_table(rows, [24 * mm, 38 * mm, 40 * mm, 20 * mm, 45 * mm], styles))

    story.append(Paragraph("How to read the charts", styles["h2"]))
    for line in (
        "<b>One colour and one marker per bank, always.</b> Navy circles are "
        "SBI, gold squares are HDFC Bank, slate triangles are ICICI Bank. The "
        "shape matters as much as the colour, so the charts work in greyscale.",
        "<b>The dotted vertical line marks the HDFC merger.</b> HDFC Bank "
        "absorbed HDFC Ltd on 1 July 2023, so FY2024 contains roughly nine "
        "months of the combined entity. A line that crosses it is not measuring "
        "one business.",
        "<b>Small differences look large in a score.</b> When only three banks "
        "are compared, the best always scores 100 and the worst always scores 0, "
        "whatever the real gap. Never read a score without the raw value.",
        "<b>A blank cell is a finding.</b> Where a number could not be sourced "
        "from a primary document it is left empty. Nothing is estimated to fill "
        "it, and a missing value is never silently treated as zero.",
        "<b>The coverage grid shows what is actually supported.</b> It marks "
        "each bank-year as human-verified, extracted but unchecked, or not "
        "found. Read it before trusting any other exhibit.",
    ):
        story.append(Paragraph(f"&bull; {line}", styles["bullet"]))

    story.append(Paragraph("What a score of 100 means - and does not mean",
                           styles["h2"]))
    story.append(Paragraph(
        "A score of 100 means the bank was the best of these three in that year. "
        "It does not mean the bank is strong in absolute terms, it does not "
        "compare against the banking system, and it is not a view on the shares. "
        "With three banks, the spread between 0 and 100 is produced by whatever "
        "difference exists, however small.", styles["body"]))

    story.append(PageBreak())
    story.append(Paragraph("Interview preparation", styles["h2"]))
    story.append(Paragraph(
        "The questions a credit or equity analyst is most likely to ask about "
        "this work, with the answers this project supports.", styles["body"]))

    qa = [
        ("Why compare standalone rather than consolidated financials?",
         "Consolidated figures include subsidiaries and joint ventures, so the "
         "comparison would reflect different group structures as much as "
         "different banking performance. Standalone isolates the bank."),
        ("Why does the HDFC merger matter so much?",
         "It changes the size of the balance sheet overnight. Any ratio computed "
         "across FY2024 partly measures the merger rather than management "
         "performance, so the merger is marked on every time series and the "
         "scorecard is run again on a merger-clean window."),
        ("Why not score net profit directly?",
         "Absolute rupees rank banks by size. SBI's balance sheet is a multiple "
         "of the other two, so a profit league table would simply reproduce a "
         "size ordering. Only ratios enter the score."),
        ("What is the difference between gross and net NPA?",
         "Gross NPA is the whole bad-loan pile. Net NPA is what remains after "
         "subtracting the provisions held against it. The gap between them is "
         "the provision coverage ratio."),
        ("Why is provision coverage ratio a trap?",
         "Because banks define it differently. A bank that includes technical "
         "write-offs in the numerator can report above 100%. That is a "
         "definitional difference, not better risk management."),
        ("Why decompose return on equity?",
         "ROE = ROA x leverage. Two banks can report the same ROE with very "
         "different risk profiles - one earning more per rupee of assets, the "
         "other simply carrying more assets per rupee of equity."),
        ("What is the sensitivity test for?",
         "The pillar weights are a judgement. Re-drawing them ten thousand times "
         "from a uniform distribution over the weight triangle turns 'I chose "
         "35/40/25' into 'the leader holds in X% of reasonable weightings'."),
        ("Why refuse to score until values are verified?",
         "Because a wrong number that looks plausible is worse than a blank. "
         "Automated extraction from annual reports can pick up a segment figure, "
         "or a multi-year row's first column, and label it as this year's bank "
         "level number. The pipeline therefore treats machine-extracted values "
         "as candidates and only scores human-verified ones."),
        ("What would falsify the conclusion?",
         "A change of weighting that moves the leader, a different normalisation "
         "method that reorders the banks, or dropping a single metric that "
         "reverses the ranking. All three are tested explicitly."),
        ("How do you know the extracted numbers are right?",
         "Each carries the document name, the page and the exact matched line. "
         "Verification means reading that line against the source. The coverage "
         "grid reports the state of every cell."),
        ("What is the biggest weakness of the study?",
         "The comparability of reported ratios across banks. Definitions of "
         "cost-to-income, provision coverage and margin denominators differ, and "
         "those differences are flagged rather than smoothed away."),
        ("Does this say anything about whether to buy the shares?",
         "No. It analyses published disclosures on a standalone basis. It "
         "contains no valuation, no forecast and no recommendation."),
    ]
    for question, answer in qa:
        story.append(Paragraph(f"<b>{question}</b>", styles["h3"]))
        story.append(Paragraph(answer, styles["body"]))

    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.8, color=RULE, spaceAfter=6))
    story.append(Paragraph(
        "Educational analysis of publicly available disclosures. Not investment "
        "advice. Bank names are used for identification only and this work is "
        "not affiliated with or reviewed by any of them.", styles["small"]))
    return story


def _memo(styles) -> list:
    """Flowables for the two-page research note."""
    story: list = []
    story.append(Paragraph("Who is India's strongest bank?", styles["title"]))
    story.append(Paragraph(
        f"An audit-grade scorecard of State Bank of India, HDFC Bank and ICICI "
        f"Bank, FY2022&ndash;FY2026 &nbsp;|&nbsp; {_build_date()}", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1.4, color=GOLD, spaceAfter=8))

    story.append(Paragraph("Position", styles["h2"]))
    story.append(Paragraph(
        "<b>The scorecard is withheld, and the withholding is the finding.</b> "
        "Scoring is locked to values a human has checked against a page. Of the "
        "80 values this study needs, 10 have been checked. Because a metric can "
        "only be scored when all three banks have a verified value in the same "
        "financial year, the locked pipeline produces no score-eligible rows at "
        "all - no overall scores, no pillar scores and no weight simulations.",
        styles["body"]))
    story.append(Paragraph(
        "That outcome is reported rather than worked around, because the "
        "alternative was measured and is worse. Automated extraction from these "
        "annual reports produced figures that pass every shape check and are "
        "wrong: State Bank of India's FY2023 net profit was read as 2,258 crore "
        "against the 50,232 crore its profit and loss statement states, and a "
        "\"profit increased by 12.88% to 80,032 crore\" sentence was read as a "
        "profit of 12.88 crore. A plausible wrong number is more damaging than a "
        "blank, so the pipeline refuses to score until the gaps are closed.",
        styles["body"]))
    story.append(Paragraph(
        "The worklist is 56 cells: 20 for HDFC Bank, 20 for State Bank of India "
        "and 16 for ICICI Bank. By metric it is 15 gross NPA, 15 net NPA, 11 "
        "return on assets, 10 return on equity and 5 net interest margin. Each "
        "carries the bank, metric, year, current status and the page to check "
        "in outputs/tables/missing_data_report.csv.", styles["body"]))

    story.append(Paragraph("Method", styles["h2"]))
    for line in (
        "<b>Sources.</b> Twenty-one primary documents - annual reports, quarterly "
        "results and investor presentations for the three banks, FY2022 to "
        "FY2026 - downloaded by hand where the issuers block automated retrieval.",
        "<b>Extraction.</b> Full text is pulled from every page (5,220 pages) and "
        "each metric is located by labelled pattern matching, with the document, "
        "page and matched line recorded against every value.",
        "<b>Verification.</b> Each candidate carries a status. Only values a "
        "human has checked against the source are marked verified; nothing "
        "machine-extracted is trusted by the scoring layer.",
        "<b>Validation.</b> Hard checks run before any scoring: net NPA may never "
        "exceed gross NPA, return on equity must exceed return on assets within a "
        "plausible leverage band, no financial year may be missing from a started "
        "series, and no currency amount may enter the score.",
        "<b>Scoring.</b> Metrics are oriented so higher is better, normalised "
        "0-100 within each year across the three banks, combined into three "
        "pillars (asset quality 35%, profitability 40%, efficiency 25%), then "
        "re-drawn across 10,000 random weightings to test whether the leader "
        "survives a change of assumptions.",
    ):
        story.append(Paragraph(f"&bull; {line}", styles["bullet"]))

    heatmap = OUT_CHARTS / "coverage_heatmap.png"
    if heatmap.exists():
        story.append(Spacer(1, 4))
        story.append(Paragraph("Verification coverage by bank, metric and year",
                               styles["h3"]))
        story.append(Image(str(heatmap), width=168 * mm, height=118 * mm))

    story.append(PageBreak())
    story.append(Paragraph("Where the evidence stands", styles["h2"]))

    coverage = OUT_TABLES / "coverage_report.csv"
    if coverage.exists():
        import pandas as pd
        frame = pd.read_csv(coverage, dtype=str, keep_default_na=False)
        rows = [[Paragraph("<b>Bank</b>", styles["cell"]),
                 Paragraph("<b>Metric</b>", styles["cell"]),
                 Paragraph("<b>Years with a value</b>", styles["cell"]),
                 Paragraph("<b>Scoring-eligible</b>", styles["cell"])]]
        for _, row in frame.head(15).iterrows():
            rows.append([Paragraph(str(row.get("bank", "")), styles["cell"]),
                         Paragraph(str(row.get("metric_name", "")), styles["cell"]),
                         Paragraph(str(row.get("with_value", "")), styles["cell"]),
                         Paragraph(str(row.get("score_eligible", "")), styles["cell"])])
        story.append(_table(rows, [20 * mm, 62 * mm, 45 * mm, 40 * mm], styles))
        story.append(Paragraph(
            "Scoring-eligible counts values that are both present and verified. "
            "It is zero throughout the current dataset, which is why no score "
            "has been produced.", styles["small"]))

    story.append(Paragraph("Risks and limitations", styles["h2"]))
    for line in (
        "<b>Cross-bank definition risk.</b> Provision coverage, cost-to-income "
        "and margin denominators are defined differently by different banks and "
        "are flagged rather than harmonised.",
        "<b>Merger distortion.</b> HDFC Bank absorbed HDFC Ltd on 1 July 2023; "
        "FY2024 contains roughly nine months of the combined entity. Every time "
        "series marks this, and a merger-clean window is reported alongside the "
        "full one.",
        "<b>Source availability.</b> ICICI Bank's annual reports for this period "
        "present ratios graphically, so those cells are recorded as not found "
        "rather than estimated.",
        "<b>Extraction risk.</b> Pattern matching over 5,220 pages can capture a "
        "segment figure or mis-date a multi-year row. This is precisely why "
        "machine output is never scored without review.",
        "<b>Scope.</b> Standalone financials only, no valuation, no forecast and "
        "no view on the securities.",
    ):
        story.append(Paragraph(f"&bull; {line}", styles["bullet"]))

    story.append(Paragraph("Document appendix", styles["h2"]))
    if SOURCE_LOG.exists():
        import pandas as pd
        log = pd.read_csv(SOURCE_LOG, dtype=str, keep_default_na=False)
        docs = sorted(set(log["document_title"]) - {""})
        rows = [[Paragraph("<b>Documents used</b>", styles["cell"])]]
        for name in docs:
            rows.append([Paragraph(name, styles["cell"])])
        story.append(_table(rows, [167 * mm], styles))
        story.append(Paragraph(
            f"{len(docs)} source document(s). Each extracted value records its "
            f"document, page number and SHA-256 of the file it came from, in "
            f"data/source_log.csv.", styles["small"]))

    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.8, color=RULE, spaceAfter=6))
    story.append(Paragraph(
        "Educational analysis of publicly available disclosures. Not investment "
        "advice and not a recommendation regarding any security. All financial "
        "data belongs to the respective banks and to the Reserve Bank of India.",
        styles["small"]))
    return story


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build_pdf(path: Path, story: list, title: str) -> Path:
    """Render one document to ``path`` with a shared header and footer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=21 * mm, rightMargin=21 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=title, author="Bank Scorecard Study",
        subject="Audit-grade comparison of three Indian banks",
    )

    def decorate(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(21 * mm, 13 * mm, A4[0] - 21 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(SLATE)
        canvas.drawString(21 * mm, 9 * mm, title)
        canvas.drawRightString(A4[0] - 21 * mm, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return path


def main() -> int:
    styles = _styles()
    DOCS.mkdir(parents=True, exist_ok=True)

    guide = build_pdf(DOCS / "understanding_guide.pdf",
                      _understanding_guide(styles),
                      "Understanding the Bank Scorecard")
    memo = build_pdf(DOCS / "case_study_memo.pdf",
                     _memo(styles),
                     "Who is India's strongest bank? - case study memo")

    for path in (guide, memo):
        size_kb = path.stat().st_size / 1024
        print(f"  wrote {path.relative_to(ROOT)}  ({size_kb:,.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
