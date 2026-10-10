"""Tests for the scorecard pipeline.

EVERY NUMBER IN THIS FILE IS AN INVENTED FIXTURE, made up to exercise the code.
None of it is real financial data. None of it is written to outputs/. None of it
may ever be quoted as a result. The fixtures exist to prove two things: that the
sanity checks actually fire, and that the scoring maths is right.
"""
import pandas as pd
import pytest

from src.load import REQUIRED_COLUMNS, normalise, scan_raw_pdfs, MANIFEST_COLUMNS
from src import validate as V
from src import scorecard as S
from src import sensitivity as SENS
from src import metrics as M
from src.config import WINDOW_PRIMARY

FIXTURE_DOC = "MOCK FIXTURE - NOT REAL DATA"


def row(bank, code, period, value, unit="pct", status="verified",
        period_type="annual", basis="standalone", **kw):
    d = {c: "" for c in REQUIRED_COLUMNS}
    d.update(
        source_id=f"{bank}-{code}-{period}", bank=bank, basis=basis,
        period_type=period_type, period_label=period, metric_code=code,
        metric_name=code,
        value_as_reported="" if value is None else str(value),
        unit_as_reported=unit, status=status,
        verification_method="same_issuer_2_docs",
        document_title=FIXTURE_DOC, document_type="fixture",
        document_date="2000-01-01", page_number="1", url="",
        downloaded_on="2000-01-01", sha256_of_document="",
        verified_by="pytest", definition_variant="", notes="invented test fixture",
    )
    d.update(kw)
    return d


def frame(rows):
    return normalise(pd.DataFrame(rows))


def series(bank, code, values, unit="pct", **kw):
    """values: dict period_label -> value"""
    return [row(bank, code, p, v, unit=unit, **kw) for p, v in values.items()]


# ---------------------------------------------------------------- units ------
def test_unit_conversion_lakh_crore():
    df = frame([row("SBI", "net_profit_inr", "FY2026", 1.0, unit="INR_lakh_crore")])
    assert df["value_normalised"].iloc[0] == pytest.approx(100_000.0)


def test_unit_conversion_billion_and_million():
    df = frame([row("SBI", "net_profit_inr", "FY2026", 1.0, unit="INR_billion"),
                row("HDFC", "net_profit_inr", "FY2026", 100.0, unit="INR_million")])
    assert set(df["value_normalised"]) == {100.0, 10.0}


def test_ratio_unit_becomes_percent():
    df = frame([row("SBI", "roa_pct", "FY2026", 0.018, unit="ratio")])
    assert df["value_normalised"].iloc[0] == pytest.approx(1.8)


def test_empty_value_is_nan_not_zero():
    """A blank cell must never silently become 0."""
    df = frame([row("SBI", "gross_npa_pct", "FY2026", None, status="UNVERIFIED")])
    assert pd.isna(df["value_normalised"].iloc[0])
    assert not bool(df["has_value"].iloc[0])


def test_unknown_unit_is_rejected():
    with pytest.raises(ValueError):
        frame([row("SBI", "net_profit_inr", "FY2026", 1.0, unit="bananas")])


# ------------------------------------------------------- scoring rules ------
def test_currency_is_never_score_eligible():
    df = frame([row("SBI", "net_profit_inr", "FY2025", 100.0, unit="INR_crore"),
                row("HDFC", "net_profit_inr", "FY2025", 50.0, unit="INR_crore")])
    assert not df["score_eligible"].any()
    assert not df["is_scored_metric"].any()


def test_unverified_row_is_not_score_eligible():
    df = frame([row("SBI", "gross_npa_pct", "FY2025", 2.0, status="UNVERIFIED")])
    assert not df["score_eligible"].any()
    assert not bool(df["is_trusted"].iloc[0])


def test_quarter_is_not_score_eligible():
    df = frame([row("SBI", "gross_npa_pct", "Q1FY2027", 2.0, period_type="quarter")])
    assert not df["score_eligible"].any()


def test_consolidated_is_dropped_by_design():
    df = frame([row("SBI", "gross_npa_pct", "FY2025", 2.0, basis="consolidated")])
    assert df.empty


# ------------------------------------------------------- hard checks -------
def test_net_npa_above_gross_npa_fails():
    df = frame([row("SBI", "gross_npa_pct", "FY2025", 2.0),
                row("SBI", "net_npa_pct", "FY2025", 2.5)])
    status, check, _ = V.check_net_npa_le_gross_npa(df)
    assert status == V.FAIL


def test_negative_npa_fails_but_negative_growth_warns():
    df = frame([row("SBI", "gross_npa_pct", "FY2025", -1.0)])
    assert V.check_impossible_values(df)[0] == V.FAIL

    df2 = frame([row("SBI", "profit_growth_pct", "FY2025", -12.0)])
    assert V.check_impossible_values(df2)[0] == V.PASS
    assert V.check_plausible_values(df2)[0] == V.WARN


def test_pcr_above_100_warns_not_fails():
    """A bank counting technical write-offs can legitimately exceed 100%."""
    df = frame([row("SBI", "pcr_pct", "FY2025", 108.0)])
    assert V.check_plausible_values(df)[0] == V.WARN
    assert V.check_impossible_values(df)[0] == V.PASS


def test_missing_year_is_a_hard_failure():
    df = frame(series("SBI", "gross_npa_pct",
                      {"FY2022": 5.0, "FY2023": 4.0, "FY2025": 2.0, "FY2026": 1.5}))
    status, _, detail = V.check_no_missing_years(df)
    assert status == V.FAIL
    assert "FY2024" in detail


def test_declared_but_unverified_year_counts_as_covered():
    """Row exists with no value + UNVERIFIED = 'we looked and could not verify'."""
    rows = series("SBI", "gross_npa_pct",
                  {p: 3.0 for p in WINDOW_PRIMARY})
    rows = [r for r in rows if r["period_label"] != "FY2024"]
    rows.append(row("SBI", "gross_npa_pct", "FY2024", None, status="UNVERIFIED"))
    assert V.check_no_missing_years(frame(rows))[0] == V.PASS


def test_full_window_passes_missing_years_check():
    df = frame(series("SBI", "gross_npa_pct", {p: 3.0 for p in WINDOW_PRIMARY}))
    assert V.check_no_missing_years(df)[0] == V.PASS


# ---------------------------------------------------- reconciliation -------
def test_roa_recompute_passes_within_tolerance():
    rows = (series("SBI", "total_assets_inr", {"FY2025": 1_000_000.0, "FY2026": 1_200_000.0},
                   unit="INR_crore")
            + [row("SBI", "net_profit_inr", "FY2026", 22_000.0, unit="INR_crore"),
               row("SBI", "roa_pct", "FY2026", 2.00)])
    assert V.check_roa_recompute(frame(rows))[0] == V.PASS


def test_roa_recompute_fails_outside_tolerance():
    rows = (series("SBI", "total_assets_inr", {"FY2025": 1_000_000.0, "FY2026": 1_200_000.0},
                   unit="INR_crore")
            + [row("SBI", "net_profit_inr", "FY2026", 22_000.0, unit="INR_crore"),
               row("SBI", "roa_pct", "FY2026", 2.50)])
    assert V.check_roa_recompute(frame(rows))[0] == V.FAIL


def test_roa_recompute_skips_when_prerequisites_absent():
    status, _, detail = V.check_roa_recompute(frame([row("SBI", "roa_pct", "FY2026", 2.0)]))
    assert status == V.SKIP
    assert "not enough" in detail


def test_pl_ladder_ties_out_and_catches_a_mismatch():
    good = [row("SBI", "nii_inr", "FY2026", 100_000.0, unit="INR_crore"),
            row("SBI", "other_income_inr", "FY2026", 20_000.0, unit="INR_crore"),
            row("SBI", "opex_inr", "FY2026", 60_000.0, unit="INR_crore"),
            row("SBI", "provisions_inr", "FY2026", 20_000.0, unit="INR_crore"),
            row("SBI", "tax_inr", "FY2026", 10_000.0, unit="INR_crore"),
            row("SBI", "net_profit_inr", "FY2026", 30_000.0, unit="INR_crore")]
    assert V.check_pl_ladder(frame(good))[0] == V.PASS

    bad = [r for r in good if r["metric_code"] != "net_profit_inr"]
    bad.append(row("SBI", "net_profit_inr", "FY2026", 35_000.0, unit="INR_crore"))
    assert V.check_pl_ladder(frame(bad))[0] == V.FAIL


# ----------------------------------------------------------- scoring -------
def test_minmax_scoring_direction_and_extremes():
    """Lower NPA is better, so the lowest NPA must score 100 and the highest 0."""
    df = frame([row("SBI", "gross_npa_pct", "FY2026", 2.0),
                row("HDFC", "gross_npa_pct", "FY2026", 1.0),
                row("ICICI", "gross_npa_pct", "FY2026", 3.0)])
    ms, _ = S.metric_scores(df)
    got = dict(zip(ms["bank"], ms["score"]))
    assert got["HDFC"] == pytest.approx(100.0)
    assert got["ICICI"] == pytest.approx(0.0)
    assert got["SBI"] == pytest.approx(50.0)


def test_degenerate_metric_gives_everyone_fifty():
    df = frame([row("SBI", "gross_npa_pct", "FY2026", 2.0),
                row("HDFC", "gross_npa_pct", "FY2026", 2.0),
                row("ICICI", "gross_npa_pct", "FY2026", 2.0)])
    ms, _ = S.metric_scores(df)
    assert set(ms["score"]) == {50.0}
    assert ms["degenerate"].all()


def test_metric_needs_two_banks_to_score():
    df = frame([row("SBI", "gross_npa_pct", "FY2026", 2.0)])
    ms, skipped = S.metric_scores(df)
    assert ms.empty and skipped


def test_overall_score_respects_weights():
    df = frame([row("SBI", "gross_npa_pct", "FY2026", 2.0),
                row("HDFC", "gross_npa_pct", "FY2026", 1.0),
                row("ICICI", "gross_npa_pct", "FY2026", 3.0)])
    ms, _ = S.metric_scores(df)
    ps = S.pillar_scores(ms)
    only_aq = S.overall_scores(ps, {"asset_quality": 1.0, "profit": 0.0, "efficiency": 0.0})
    got = dict(zip(only_aq["bank"], only_aq["overall"]))
    assert got["HDFC"] == pytest.approx(100.0)
    assert got["ICICI"] == pytest.approx(0.0)


# ------------------------------------------------------- sensitivity -------
def _scorecard_frame():
    """One metric per pillar, three banks, full window. Invented values."""
    specs = {
        "gross_npa_pct": {"SBI": 3.0, "HDFC": 1.3, "ICICI": 2.4},
        "roa_pct":       {"SBI": 0.9, "HDFC": 1.9, "ICICI": 2.2},
        "cost_to_income_pct": {"SBI": 52.0, "HDFC": 39.0, "ICICI": 41.0},
    }
    rows = []
    for code, per_bank in specs.items():
        for bank, base in per_bank.items():
            for i, period in enumerate(WINDOW_PRIMARY):
                rows.append(row(bank, code, period, base + i * 0.1))
    return frame(rows)


def test_win_shares_are_probabilities_that_sum_to_one():
    df = _scorecard_frame()
    ps = S.pillar_scores(S.metric_scores(df)[0])
    shares = SENS.random_win_shares(ps, n=2000, seed=42)
    for col in ["p_rank1", "p_rank2", "p_rank3"]:
        assert shares[col].sum() == pytest.approx(1.0, abs=1e-9)
    assert len(shares) == 3


def test_sensitivity_is_deterministic_with_fixed_seed():
    df = _scorecard_frame()
    ps = S.pillar_scores(S.metric_scores(df)[0])
    a = SENS.random_win_shares(ps, n=1500, seed=42)
    b = SENS.random_win_shares(ps, n=1500, seed=42)
    pd.testing.assert_frame_equal(a, b)


def test_flip_ranges_cover_the_base_weight():
    df = _scorecard_frame()
    ps = S.pillar_scores(S.metric_scores(df)[0])
    flips = SENS.flip_ranges(ps, step=0.02)
    assert len(flips) == 3
    for _, r in flips.iterrows():
        assert r["range_low"] <= r["base_weight"] <= r["range_high"]


def test_simplex_grid_weights_sum_to_one():
    df = _scorecard_frame()
    ps = S.pillar_scores(S.metric_scores(df)[0])
    grid = SENS.simplex_grid(ps, step=0.25)
    tot = grid[["w_asset_quality", "w_profit", "w_efficiency"]].sum(axis=1)
    assert tot.round(6).eq(1.0).all()


def test_leave_one_out_flags_no_change_on_invented_data():
    df = _scorecard_frame()
    table, base_winner = SENS.metric_leave_one_out(df)
    assert base_winner in {"SBI", "HDFC", "ICICI"}
    assert set(table["dropped_metric"]) == set(df[df.is_scored_metric]["metric_code"])


# ------------------------------------------------- graceful raw scanning ----
def test_scan_raw_pdfs_with_no_pdfs_is_graceful(tmp_path, monkeypatch):
    """No data/raw content must be a warning, never a crash."""
    import src.load as L
    monkeypatch.setattr(L, "RAW", tmp_path)
    out = L.scan_raw_pdfs(verbose=False)
    assert out.empty
    assert list(out.columns) == MANIFEST_COLUMNS


def test_scan_raw_pdfs_on_a_broken_pdf_does_not_crash(tmp_path, monkeypatch):
    import src.load as L
    bad = tmp_path / "hdfc" / "not-really.pdf"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"this is not a pdf")
    monkeypatch.setattr(L, "RAW", tmp_path)
    out = L.scan_raw_pdfs(verbose=False)
    assert len(out) == 1
    assert out["status"].iloc[0] in {"unreadable", "scanned_image"}


def test_scan_raw_pdfs_reports_a_readable_pdf_as_ok(tmp_path, monkeypatch):
    """Regression test for the bug that made every real annual report 'unreadable'.

    pdfplumber read the text and the tables correctly, then the dump path could
    not be built (an undefined name), the exception was caught by the broad
    handler at the bottom of the loop, and all 21 real PDFs were reported as
    unreadable while holding perfectly good extractions. A readable document must
    come back as 'ok' with a note that is empty, and its dumps must exist on disk.
    """
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    import src.load as L

    raw = tmp_path / "raw"
    (raw / "hdfc").mkdir(parents=True)
    pdf_path = raw / "hdfc" / "tiny.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(72, 720, "Gross NPA 1.23 per cent of gross advances for the year")
    c.showPage()
    c.drawString(72, 720, "Net Interest Margin 3.45 per cent on average assets")
    c.save()

    monkeypatch.setattr(L, "RAW", raw)
    monkeypatch.setattr(L, "ROOT", tmp_path)
    monkeypatch.setattr(L, "EXTRACT_DIR", tmp_path / "extracted")

    out = L.scan_raw_pdfs(verbose=False)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["status"] == "ok", f"expected ok, got {r['status']}: {r['note']}"
    assert r["note"] == ""
    assert r["pages"] == 2
    assert r["text_chars"] > 0
    assert r["text_dump"] and (tmp_path / r["text_dump"]).exists()
    if r["tables_found"]:
        assert r["tables_dump"] and (tmp_path / r["tables_dump"]).exists()


# --------------------------------------------------- profit quality -------
def _pl(bank, period, nii, oi, opex, prov, tax):
    """One year of an invented P&L, with net profit derived from the ladder."""
    pat = nii + oi - opex - prov - tax
    return [row(bank, "nii_inr", period, nii, unit="INR_crore"),
            row(bank, "other_income_inr", period, oi, unit="INR_crore"),
            row(bank, "opex_inr", period, opex, unit="INR_crore"),
            row(bank, "provisions_inr", period, prov, unit="INR_crore"),
            row(bank, "tax_inr", period, tax, unit="INR_crore"),
            row(bank, "net_profit_inr", period, pat, unit="INR_crore")]


def test_profit_quality_is_operations_led_when_provisions_do_not_move():
    df = frame(_pl("SBI", "FY2025", 100_000, 20_000, 60_000, 20_000, 10_000)
               + _pl("SBI", "FY2026", 110_000, 20_000, 60_000, 20_000, 10_000))
    got = M.profit_quality(df).set_index("period_label").loc["FY2026"]
    assert got["d_pat_inr"] == pytest.approx(10_000.0)
    assert got["pat_from_operations_inr"] == pytest.approx(10_000.0)
    assert got["pat_from_provisions_inr"] == pytest.approx(0.0)
    assert got["share_from_operations_pct"] == pytest.approx(100.0)
    assert got["quality_verdict"] == "operations-led"


def test_profit_quality_is_provision_led_when_only_provisions_fall():
    """Flat operating profit, provisions down 10,000: the rise is not earned."""
    df = frame(_pl("HDFC", "FY2025", 100_000, 20_000, 60_000, 30_000, 10_000)
               + _pl("HDFC", "FY2026", 100_000, 20_000, 60_000, 20_000, 10_000))
    got = M.profit_quality(df).set_index("period_label").loc["FY2026"]
    assert got["d_operating_profit_inr"] == pytest.approx(0.0)
    assert got["pat_from_provisions_inr"] == pytest.approx(10_000.0)
    assert got["share_from_provisions_pct"] == pytest.approx(100.0)
    assert got["quality_verdict"] == "provision-led"


def test_profit_quality_identity_closes():
    """The three contributions must add back to the actual change in net profit."""
    df = frame(_pl("ICICI", "FY2025", 100_000, 20_000, 60_000, 30_000, 10_000)
               + _pl("ICICI", "FY2026", 104_000, 22_000, 63_000, 24_000, 11_000))
    got = M.profit_quality(df).set_index("period_label").loc["FY2026"]
    assert got["identity_residual_inr"] == pytest.approx(0.0, abs=1e-9)
    total = (got["pat_from_operations_inr"] + got["pat_from_provisions_inr"]
             + got["pat_from_tax_inr"])
    assert total == pytest.approx(got["d_pat_inr"])


def test_profit_quality_missing_input_gives_blank_not_a_guess():
    rows = _pl("SBI", "FY2025", 100_000, 20_000, 60_000, 20_000, 10_000)
    rows += [r for r in _pl("SBI", "FY2026", 110_000, 20_000, 60_000, 20_000, 10_000)
             if r["metric_code"] != "opex_inr"]        # operating expenses withheld
    got = M.profit_quality(frame(rows)).set_index("period_label").loc["FY2026"]
    assert got["d_operating_profit_inr"] is None or pd.isna(got["d_operating_profit_inr"])
    assert got["share_from_operations_pct"] is None or pd.isna(got["share_from_operations_pct"])
    assert got["quality_verdict"] == ""
    assert "missing" in got["note"]


def test_profit_quality_flags_the_hdfc_merger_year_only():
    """FY2024 is HDFC's transition year; the flag must not spread to other banks."""
    rows = (_pl("HDFC", "FY2023", 100_000, 20_000, 60_000, 20_000, 10_000)
            + _pl("HDFC", "FY2024", 140_000, 30_000, 90_000, 20_000, 15_000)
            + _pl("SBI", "FY2023", 100_000, 20_000, 60_000, 20_000, 10_000)
            + _pl("SBI", "FY2024", 110_000, 20_000, 60_000, 20_000, 10_000))
    out = M.profit_quality(frame(rows)).set_index(["bank", "period_label"])
    assert bool(out.loc[("HDFC", "FY2024"), "merger_affected"])
    assert not bool(out.loc[("SBI", "FY2024"), "merger_affected"])
    assert not bool(out.loc[("HDFC", "FY2023"), "merger_affected"])
    assert "merger" in out.loc[("HDFC", "FY2024"), "note"]


def test_profit_quality_declines_to_share_out_a_fall():
    """A share of a decline is not a meaningful sentence - leave it blank."""
    df = frame(_pl("SBI", "FY2025", 100_000, 20_000, 60_000, 20_000, 10_000)
               + _pl("SBI", "FY2026", 90_000, 20_000, 60_000, 20_000, 10_000))
    got = M.profit_quality(df).set_index("period_label").loc["FY2026"]
    assert got["d_pat_inr"] < 0
    assert got["share_from_operations_pct"] is None or pd.isna(got["share_from_operations_pct"])
    assert got["quality_verdict"] == "no profit growth to decompose"


# ----------------------------------------------------------- structure -----
def test_required_columns_are_stable():
    assert len(REQUIRED_COLUMNS) == 22
    assert REQUIRED_COLUMNS[0] == "source_id"
