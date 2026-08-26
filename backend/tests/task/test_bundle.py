"""
Research bundle + offline verifier tests (docs/12 M12).

Three layers:

1. The pure assembler (round-trip, hash integrity, claim extraction).
2. The verifier (tamper detection, citation resolution, approval chain, trace status).
3. The CLI entry point (file-based round-trip, exit codes).

No DB, no model — everything is exercised against synthetic data.
"""

from __future__ import annotations

import json

from evals.metrics import claim_lines
from research_engine.bundle import (
    BundleManifest,
    assemble,
    compute_bundle_hash,
    content_hash,
    serialize,
)
from research_engine.verify_bundle import (
    format_json,
    format_text,
    main,
    verify,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────────

_REPORT = (
    "# Test Report\n\n"
    "## Executive Summary\n\n"
    "The electric vehicle market grew significantly in 2024 [1]. "
    "Solar installations led the growth [2].\n\n"
    "## Sources\n\n"
    "[1] https://example.org/ev-market\n"
    "[2] https://example.org/solar-growth\n"
)

_EVIDENCE = [
    {
        "task_id": 1,
        "source_url": "https://example.org/ev-market",
        "source_title": "EV Market Report",
        "snippet": "Global electric vehicle sales reached 17.1 million units in 2024.",
        "key_fact": "EV sales were 17.1 million in 2024",
    },
    {
        "task_id": 1,
        "source_url": "https://example.org/solar-growth",
        "source_title": "Solar Growth Report",
        "snippet": "Solar installations accounted for three-quarters of renewable growth.",
        "key_fact": "Solar was 75% of growth",
    },
]

_SOURCES = [
    {
        "index": 1,
        "url": "https://example.org/ev-market",
        "title": "EV Market Report",
        "snippet": "",
    },
    {
        "index": 2,
        "url": "https://example.org/solar-growth",
        "title": "Solar Growth Report",
        "snippet": "",
    },
]

_APPROVAL = [
    {
        "action": "approved",
        "feedback": None,
        "draft_hash": content_hash(_REPORT),
        "timestamp": "2026-08-13T12:00:00+00:00",
    },
]

_TRACE = [
    {"type": "agent_log", "agent": "planner", "message": "Decomposing query…"},
    {"type": "agent_log", "agent": "executor", "message": "Searching…"},
]


def _bundle(**overrides) -> BundleManifest:
    """Build a valid bundle with sensible defaults."""
    kwargs = dict(
        session_id="test-session-1",
        query="EV market growth in 2024",
        report=_REPORT,
        evidence=_EVIDENCE,
        sources=_SOURCES,
        approval_chain=_APPROVAL,
        trace=_TRACE,
        trace_available=True,
        models={"planner": "ollama:qwen2.5", "executor": "ollama:qwen2.5"},
        cost_usd=0.0,
    )
    kwargs.update(overrides)
    return assemble(**kwargs)


# ── 1. Round-trip: assemble → serialize → parse → verify ──────────────────────────


def test_round_trip():
    bundle = _bundle()
    text = serialize(bundle)
    parsed = BundleManifest.model_validate_json(text)
    result = verify(parsed)
    assert result.passed, format_text(result)
    assert all(c.passed for c in result.checks)


# ── 2. Tamper detection — snippet ─────────────────────────────────────────────────


def test_tampered_snippet_detected():
    bundle = _bundle()
    # Tamper: mutate a snippet after assembly
    bundle.evidence[0].snippet = "TAMPERED TEXT"
    # Recompute bundle_hash so only the evidence check catches it
    bundle.bundle_hash = compute_bundle_hash(bundle)
    bundle.report_hash = content_hash(bundle.report)
    result = verify(bundle)
    assert not result.passed
    evidence_check = next(c for c in result.checks if c.name == "evidence_integrity")
    assert not evidence_check.passed
    assert "tampered" in evidence_check.detail.lower()
    assert "example.org/ev-market" in evidence_check.detail


# ── 3. Tamper detection — bundle-level ────────────────────────────────────────────


def test_tampered_report_breaks_bundle_hash():
    bundle = _bundle()
    # Tamper: modify report text without updating bundle_hash
    bundle.report = bundle.report + "\n\nINJECTED CONTENT"
    result = verify(bundle)
    assert not result.passed
    bundle_check = next(c for c in result.checks if c.name == "bundle_integrity")
    assert not bundle_check.passed
    assert "modified after assembly" in bundle_check.detail


# ── 4. Tamper detection — report hash ─────────────────────────────────────────────


def test_tampered_report_with_updated_hash_but_not_bundle():
    """Overwrite report + report_hash but not bundle_hash → bundle integrity fails."""
    bundle = _bundle()
    bundle.report = "# Fake report\n\nNo evidence.\n"
    bundle.report_hash = content_hash(bundle.report)
    # NOT updating bundle_hash — so bundle_integrity catches it
    result = verify(bundle)
    assert not result.passed
    bundle_check = next(c for c in result.checks if c.name == "bundle_integrity")
    assert not bundle_check.passed


# ── 5. Unresolved citation ────────────────────────────────────────────────────────


def test_unresolved_citation():
    report_with_bad_cite = _REPORT.replace("[2].", "[2][99].")
    bundle = _bundle(report=report_with_bad_cite)
    result = verify(bundle)
    assert not result.passed
    cite_check = next(c for c in result.checks if c.name == "citation_resolution")
    assert not cite_check.passed
    assert "99" in cite_check.detail


# ── 6. Missing approval ──────────────────────────────────────────────────────────


def test_missing_approval():
    bundle = _bundle(approval_chain=[])
    result = verify(bundle)
    assert not result.passed
    approval_check = next(c for c in result.checks if c.name == "approval_chain")
    assert not approval_check.passed
    assert "never human-reviewed" in approval_check.detail


# ── 7. Approval hash mismatch ────────────────────────────────────────────────────


def test_approval_hash_mismatch():
    """Approval chain has 'approved' but draft_hash doesn't match report_hash."""
    bad_approval = [
        {
            "action": "approved",
            "feedback": None,
            "draft_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            "timestamp": "2026-08-13T12:00:00+00:00",
        },
    ]
    bundle = _bundle(approval_chain=bad_approval)
    result = verify(bundle)
    assert not result.passed
    approval_check = next(c for c in result.checks if c.name == "approval_chain")
    assert not approval_check.passed
    assert "does not apply to this report" in approval_check.detail


# ── 8. Trace unavailable ─────────────────────────────────────────────────────────


def test_trace_unavailable():
    bundle = _bundle(trace=[], trace_available=False)
    result = verify(bundle)
    # trace_available=false is NOT a failure — it's a note
    assert result.passed, format_text(result)
    assert any("without durable event logging" in n for n in result.notes)


# ── 9. Trace tampered → bundle_hash breaks ────────────────────────────────────────


def test_trace_inside_bundle_hash():
    """Modifying trace after assembly breaks bundle_hash — proves trace is hashed."""
    bundle = _bundle()
    bundle.trace.append({"type": "injected", "agent": "evil"})
    result = verify(bundle)
    assert not result.passed
    bundle_check = next(c for c in result.checks if c.name == "bundle_integrity")
    assert not bundle_check.passed


# ── 10. Claims extraction matches evals.metrics ──────────────────────────────────


def test_claims_match_metrics():
    bundle = _bundle()
    metric_claims = claim_lines(bundle.report)
    bundle_sentences = [c.sentence for c in bundle.claims]
    assert bundle_sentences == metric_claims


# ── 11. CLI round-trip ────────────────────────────────────────────────────────────


def test_cli_passes_valid_bundle(tmp_path):
    bundle = _bundle()
    p = tmp_path / "test.bundle.json"
    p.write_text(serialize(bundle), encoding="utf-8")
    exit_code = main([str(p)])
    assert exit_code == 0


def test_cli_fails_tampered_bundle(tmp_path):
    bundle = _bundle()
    text = serialize(bundle)
    data = json.loads(text)
    data["report"] = "TAMPERED"
    p = tmp_path / "bad.bundle.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    exit_code = main([str(p)])
    assert exit_code == 1


def test_cli_json_format(tmp_path):
    bundle = _bundle()
    p = tmp_path / "test.bundle.json"
    p.write_text(serialize(bundle), encoding="utf-8")
    exit_code = main([str(p), "--format", "json"])
    assert exit_code == 0


def test_cli_bad_file(tmp_path):
    p = tmp_path / "nonexistent.json"
    exit_code = main([str(p)])
    assert exit_code == 1


# ── Format output tests ──────────────────────────────────────────────────────────


def test_format_text_shows_verdict():
    result = verify(_bundle())
    text = format_text(result)
    assert "PASS" in text
    assert "✓" in text


def test_format_json_round_trips():
    result = verify(_bundle())
    data = json.loads(format_json(result))
    assert data["passed"] is True
    assert len(data["checks"]) >= 7


# ── Demo provenance (docs/17 §6.2) ────────────────────────────────────────────────


def test_real_bundle_is_not_marked_demo():
    """The default must be "real". Mislabelling real work as a demo is recoverable;
    the inverse is not, so the flag defaults off."""
    result = verify(_bundle())
    assert result.demo is False
    assert "DEMO" not in format_text(result)
    assert json.loads(format_json(result))["demo"] is False


def test_demo_bundle_announces_itself_above_the_verdict():
    """A demo bundle passes every integrity check — its hashes are real hashes of
    scripted output — so PASS alone is true and dangerously misleading. The warning has
    to be the first thing read, not a note after the checks."""
    result = verify(_bundle(demo=True))
    assert result.passed is True, "a demo bundle is still internally consistent"
    assert result.demo is True

    text = format_text(result)
    assert "DEMO BUNDLE" in text
    assert "NOT REAL RESEARCH" in text
    # Above the verdict, not merely present somewhere in the output.
    assert text.index("DEMO BUNDLE") < text.index("Bundle verification:")
    assert json.loads(format_json(result))["demo"] is True


def test_demo_flag_cannot_be_edited_away():
    """Laundering a demo bundle into a real-looking one must break verification.

    Without this the stamp is advisory: anyone could flip one boolean in the JSON and
    pass scripted output off as research. `bundle_hash` covers the flag, so the edit is
    caught by the same check that catches a doctored report.
    """
    honest = _bundle(demo=True)
    assert verify(honest).passed is True

    doctored = BundleManifest(**{**json.loads(serialize(honest)), "demo": False})
    integrity = next(c for c in verify(doctored).checks if c.name == "bundle_integrity")
    assert integrity.passed is False, "flipping demo must break the bundle hash"


# ── The verifier has to produce a verdict on the machine it is run on ──────────────


def test_the_verifier_falls_back_to_ascii_when_the_console_cannot_render_glyphs():
    """A Windows console is cp1252, and `✓` is not in cp1252.

    Found by driving the packaged desktop sidecar on a Windows runner: every check passed,
    and then `print` raised `UnicodeEncodeError` — a traceback where the word PASS should
    have been. This is the one program in the repository a stranger runs on their own
    machine to check an artifact they were handed, so "it works on the developer's
    terminal" is not the bar.

    ASCII markers, not `errors="replace"`: a row of `?` beside each check would render but
    would leave a reader unable to tell a pass from a failure, which is the only thing this
    output exists to say.
    """
    import io

    from research_engine import verify_bundle as vb

    result = vb.verify(_bundle())
    cp1252 = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")

    text = vb.format_text(result, stream=cp1252)
    text.encode("cp1252")  # must not raise — that is the whole failure being fixed
    assert "[PASS]" in text or "[FAIL]" in text
    assert "✓" not in text and "✗" not in text

    utf8 = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    assert "✓" in vb.format_text(result, stream=utf8), "a capable console keeps the glyphs"


def test_the_whole_report_degrades_not_just_the_tick_marks():
    """The demo banner carries an em dash, which a strict-ASCII console cannot encode either.

    Fixing only the check marks would move the crash one line down — and it would move it
    onto the banner that says the bundle is *scripted output, not real research*, which is
    the single most important line in this program's output.
    """
    import io

    from research_engine import verify_bundle as vb

    result = vb.verify(_bundle(demo=True))
    ascii_only = io.TextIOWrapper(io.BytesIO(), encoding="ascii")

    text = vb.format_text(result, stream=ascii_only)
    text.encode("ascii")  # must not raise
    assert "DEMO BUNDLE" in text, "the demo warning must survive the degradation"
    assert "NOT REAL RESEARCH" in text
