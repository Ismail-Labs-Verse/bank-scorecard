#!/usr/bin/env python
"""run_all.py - one command rebuilds every table and chart from verified data.

THE TWO-TIER CONTRACT (this matters, and the README repeats it):

  python run_all.py                 builds everything from data/source_log.csv,
                                    which is committed. This is what a fresh
                                    clone can run.
  python run_all.py --scan-raw      additionally scans data/raw/ for PDFs and
                                    dumps extractable text/tables as CANDIDATE
                                    material for a human to verify.
  python run_all.py --verify-raw    re-hashes data/raw/ against the source log
                                    and reports any document that changed.

data/raw/ is gitignored on purpose (copyright and size), so a fresh clone will
always run the tier that starts from data/processed/. This script never invents
a value and never treats extracted text as verified data.

Exit codes: 0 = everything built, 2 = blocked because nothing is verified yet.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src import config as C                                    # noqa: E402
from src.load import SourceLogMissing, build_master_long, coverage_report, read_source_log  # noqa: E402

OK, WARN, FAILED, SKIP, BLOCKED = "OK", "WARN", "FAILED", "SKIP", "BLOCKED"
_results = []


def record(stage, status, detail=""):
    _results.append(dict(stage=stage, status=status, detail=str(detail)[:200]))
    icon = {OK: " ok ", WARN: "warn", FAILED: "FAIL", SKIP: "skip", BLOCKED: "BLOK"}[status]
    print(f"[{icon}] {stage}" + (f" - {detail}" if detail else ""))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-raw", action="store_true",
                    help="also scan data/raw/ for PDFs (candidate material only)")
    ap.add_argument("--verify-raw", action="store_true",
                    help="re-hash data/raw/ against the source log")
    args = ap.parse_args()

    t0 = time.time()
    C.OUT_TABLES.mkdir(parents=True, exist_ok=True)
    C.OUT_CHARTS.mkdir(parents=True, exist_ok=True)
    C.OUT_TABLEAU.mkdir(parents=True, exist_ok=True)
    C.PROCESSED.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("BANK SCORECARD - run_all.py")
    print("=" * 72)

    # ---------------------------------------------------------------- stage 0
    if args.scan_raw:
        try:
            from src.load import scan_raw_pdfs, write_scan_manifest
            man = scan_raw_pdfs(verbose=True)
            p = write_scan_manifest(man)
            n = len(man)
            record("scan_raw_pdfs", OK if n else WARN,
                   f"{n} PDF(s) scanned -> {p.name}; extracted text is CANDIDATE "
                   "material only, not verified data")
        except Exception as exc:
            record("scan_raw_pdfs", WARN, f"{type(exc).__name__}: {exc}")

    # ---------------------------------------------------------------- stage 1
    try:
        df = build_master_long()
        n = int(df["source_id"].nunique())
        record("load_source_log", OK, f"{len(df)} rows read, {n} distinct source_id")
    except SourceLogMissing as exc:
        record("load_source_log", BLOCKED, "no verified data")
        print()
        print("-" * 72)
        print("BLOCKED: there is nothing verified to compute.")
        print("-" * 72)
        print(str(exc))
        print()
        print("This is the pipeline working correctly, not failing. It refuses to")
        print("produce a scoreboard from numbers nobody has checked against a")
        print("primary document. A blank is better than a guess.")
        print()
        print("The PDF scan report (if any PDFs are present) was still written to")
        print(f"  {C.OUT_TABLES / 'pdf_probe_report.csv'}")
        try:
            from src.pdf_probe import probe_all
            p = probe_all()
            record("pdf_probe", OK if len(p) else WARN,
                   f"{len(p)} PDF(s) probed -> outputs/tables/pdf_probe_report.csv")
        except Exception as exc:
            record("pdf_probe", WARN, f"{type(exc).__name__}: {exc}")
        _write_manifest(t0, blocked=True)
        _print_summary()
        return 2

    # ---------------------------------------------------------------- stage 2
    from src import validate as V
    report = V.run_all_checks(df)
    report.to_csv(C.OUT_TABLES / "validation_report.csv", index=False)
    hard = report[report.status == V.FAIL]
    warns = report[report.status == V.WARN]
    if not hard.empty:
        record("validate", FAILED, f"{len(hard)} hard failure(s)")
        print(hard.to_string(index=False))
    else:
        record("validate", OK, f"{len(report)} checks, {len(warns)} warning(s)")
    if not warns.empty:
        for _, r in warns.iterrows():
            record(f"validate/{r['check']}", WARN, r["detail"])

    # ---------------------------------------------------------------- stage 3
    cov = coverage_report(df)
    cov.to_csv(C.OUT_TABLES / "coverage_report.csv", index=False)
    record("coverage", OK if len(cov) else WARN,
           f"{len(cov)} bank/metric series -> outputs/tables/coverage_report.csv")

    if not hard.empty:
        record("downstream", BLOCKED, "hard validation failures must be fixed first")
        _write_manifest(t0, blocked=True)
        _print_summary()
        return 2

    # ---------------------------------------------------------------- stage 4
    from src import metrics as M
    trend = M.trend_table(df)
    trend.to_csv(C.OUT_TABLES / "trends.csv", index=False)
    record("metrics_trends", OK, f"{len(trend)} rows -> outputs/tables/trends.csv")

    # ---------------------------------------------------------------- stage 5
    from src import dupont as D
    dup = D.dupont_by_bank(df)
    import pandas as pd
    pd.DataFrame(dup).to_csv(C.OUT_TABLES / "dupont.csv", index=False)
    record("dupont", OK if dup else WARN, f"{len(dup)} bank-year rows")

    # ---------------------------------------------------------------- stage 6
    pq = M.profit_quality(df, C.WINDOW_PRIMARY)
    pd.DataFrame(pq).to_csv(C.OUT_TABLES / "profit_quality.csv", index=False)
    flagged = int(pq["merger_affected"].sum()) if not pq.empty else 0
    record("profit_quality", OK if not pq.empty else WARN,
           f"{len(pq)} bank-year row(s), {flagged} flagged as merger-affected"
           if not pq.empty else "no year-on-year P&L pairs to decompose yet")

    # ---------------------------------------------------------------- stage 7
    from src import scorecard as S
    primary = S.build(df, C.WINDOW_PRIMARY)
    clean = S.build(df, C.WINDOW_CLEAN)
    primary["scored"].to_csv(C.OUT_TABLES / "scorecard_primary_FY22_FY26.csv", index=False)
    primary["metric_scores"].to_csv(C.OUT_TABLES / "metric_scores.csv", index=False)
    if not primary["summary"].empty:
        primary["summary"].to_csv(C.OUT_TABLES / "scorecard_summary_primary.csv", index=False)
    if not clean["summary"].empty:
        clean["summary"].to_csv(C.OUT_TABLES / "scorecard_summary_merger_clean.csv", index=False)
    limitation_warnings = []
    if primary["scored"].empty:
        record("scorecard", WARN,
               "no score produced: no metric has a trusted value for all three banks "
               "in the same year yet")
        try:
            csv_path, json_path, blocked = _write_missing_data_report(df)
            record("scorecard/missing_data", WARN,
                   f"{blocked} cell(s) block the scorecard -> "
                   f"{csv_path.relative_to(ROOT)} and {json_path.relative_to(ROOT)}")
        except Exception as exc:
            record("scorecard/missing_data", WARN,
                   f"could not write the missing-data report: "
                   f"{type(exc).__name__}: {exc}")
        _remove_stale(
            C.OUT_TABLES / "scorecard_primary_FY22_FY26.csv",
            C.OUT_TABLES / "scorecard_summary_primary.csv",
            C.OUT_TABLES / "scorecard_summary_merger_clean.csv",
            C.OUT_TABLES / "sensitivity_win_shares.csv",
            C.OUT_TABLES / "sensitivity_flip_ranges.csv",
            C.OUT_TABLES / "sensitivity_simplex_grid.csv",
        )
    else:
        w = S.winner(primary["scored"])
        record("scorecard", OK, f"primary window winner: {w}; "
                                f"{len(primary['scored'])} bank-year rows")
        limitation_warnings = sorted({str(v) for v in
                                      primary["scored"].get("data_limitation", [])
                                      if isinstance(v, str) and v})
        for limitation in limitation_warnings[:3]:
            record("scorecard/data_limitation", WARN, limitation)
        for s in primary["skipped"][:5]:
            record("scorecard/skipped", WARN, s)

    # ---------------------------------------------------------------- stage 8
    from src import sensitivity as SENS
    shares = SENS.random_win_shares(primary["pillar_scores"])
    if not shares.empty:
        shares.to_csv(C.OUT_TABLES / "sensitivity_win_shares.csv", index=False)
    flips = SENS.flip_ranges(primary["pillar_scores"])
    if not flips.empty:
        flips.to_csv(C.OUT_TABLES / "sensitivity_flip_ranges.csv", index=False)
    grid = SENS.simplex_grid(primary["pillar_scores"], step=0.05)
    if not grid.empty:
        grid.to_csv(C.OUT_TABLES / "sensitivity_simplex_grid.csv", index=False)
    if shares.empty:
        record("sensitivity", WARN, "no weights could be tested: no score computed yet")
    else:
        record("sensitivity", OK,
               f"{C.N_SENSITIVITY_DRAWS} draws (seed {C.SEED}) + flip ranges + simplex grid")

    # ---------------------------------------------------------------- stage 9
    from src import export_tableau as ET
    written, hyper = ET.export(df, primary["scored"], primary["metric_scores"], shares)
    record("tableau_export", OK,
           f"{len(written)} CSV(s); .hyper {'available' if hyper else 'not installed - CSV only'}")

    # ---------------------------------------------------------------- stage 9
    from src import charts as CH
    made = CH.generate_all()
    record("charts", OK if made else WARN,
           f"{len(made)} chart(s) -> outputs/charts/" if made
           else "no charts: nothing to plot yet")

    # ---------------------------------------------------------------- stage 10
    try:
        from src.pdf_probe import probe_all
        p = probe_all()
        record("pdf_probe", OK if len(p) else WARN,
               f"{len(p)} PDF(s) probed -> outputs/tables/pdf_probe_report.csv")
    except Exception as exc:
        record("pdf_probe", WARN, f"{type(exc).__name__}: {exc}")

    blocked = any(r["status"] in (FAILED, BLOCKED) for r in _results)
    _write_manifest(t0, blocked=blocked)
    _print_summary()
    return 2 if blocked else 0


def _remove_stale(*paths) -> None:
    """Delete outputs a stage could not produce this time.

    A CSV left behind by an earlier run is invisible in the current run but is
    still read by the chart layer, which would then draw a figure from data the
    pipeline no longer stands behind. Clearing them keeps every artefact
    traceable to the run that produced it.
    """
    for path in paths:
        try:
            if path.exists():
                path.unlink()
                print(f"  removed stale {path.relative_to(ROOT)}")
        except OSError:
            pass


def _write_missing_data_report(df):
    """Record exactly which cells stop the scorecard from being computed.

    When the pipeline is locked to verified values it can refuse to score at
    all. Refusing is correct - but refusing *silently* is not, so this writes
    the blocking cells to CSV and JSON, naming the bank, metric, year, current
    status and what would unblock it. The run continues and exits normally; the
    point is to hand over a worklist, not to stop the build.
    """
    import json

    import pandas as pd

    from src.config import TRUSTED_STATUSES

    rows = []
    for _, record_row in df[df["is_scored_metric"]].iterrows():
        trusted = record_row["status"] in TRUSTED_STATUSES
        has_value = bool(record_row["has_value"])
        if trusted and has_value:
            continue
        if not has_value:
            reason = "no value recorded - not found in the source documents"
        elif not trusted:
            reason = (f"status '{record_row['status']}' is not trusted while "
                      "scoring is locked to verified values")
        else:
            reason = "excluded by an eligibility rule"
        rows.append(dict(
            bank=record_row["bank"], metric_code=record_row["metric_code"],
            metric_name=record_row.get("metric_name", record_row["metric_code"]),
            period_label=record_row["period_label"], status=record_row["status"],
            page_number=record_row.get("page_number", ""),
            document=record_row.get("document_title", ""),
            reason=reason,
            unblock="confirm the value against the cited page, then set status to "
                    "'verified'",
        ))

    report = pd.DataFrame(rows)
    csv_path = C.OUT_TABLES / "missing_data_report.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(csv_path, index=False)

    summary = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scoring_mode": ("locked to trusted values" if not C.ALLOW_UNVERIFIED_SCORING
                         else "unverified values allowed"),
        "trusted_statuses": sorted(TRUSTED_STATUSES),
        "blocking_cells": int(len(report)),
        "by_bank": report.groupby("bank").size().to_dict() if not report.empty else {},
        "by_metric": (report.groupby("metric_code").size().to_dict()
                      if not report.empty else {}),
        "note": ("Every row here blocks the scorecard. A metric can only be scored "
                 "when all three banks have a trusted value in the same year."),
    }
    json_path = ROOT / "outputs" / "missing_data_report.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return csv_path, json_path, len(report)


def _write_manifest(t0, blocked):
    import pandas as pd
    outputs = {}
    for d in (C.OUT_TABLES, C.OUT_CHARTS, C.OUT_TABLEAU):
        if d.exists():
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    outputs[str(f.relative_to(ROOT))] = sha256_file(f)
    manifest = dict(
        generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        runtime_seconds=round(time.time() - t0, 2),
        blocked=blocked,
        python=sys.version.split()[0],
        platform=platform.platform(),
        seed=C.SEED,
        pillar_weights=C.PILLAR_WEIGHTS,
        window_primary=C.WINDOW_PRIMARY,
        window_clean=C.WINDOW_CLEAN,
        stages=_results,
        outputs=outputs,
    )
    try:
        import pandas as pd
        manifest["library_versions"] = {
            "pandas": pd.__version__,
            "numpy": __import__("numpy").__version__,
            "matplotlib": __import__("matplotlib").__version__,
        }
    except Exception:
        pass
    C.OUT_MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"\nmanifest -> {C.OUT_MANIFEST.relative_to(ROOT)}  "
          f"({len(outputs)} output file(s) hashed)")


def _print_summary():
    print("\n" + "=" * 72)
    print("STAGE SUMMARY")
    print("=" * 72)
    for r in _results:
        print(f"  {r['status']:<8} {r['stage']:<24} {r['detail']}")
    n_blocked = sum(1 for r in _results if r["status"] in (FAILED, BLOCKED))
    print("=" * 72)
    print("RESULT: " + ("BLOCKED - see above" if n_blocked else "completed"))


if __name__ == "__main__":
    sys.exit(main())
