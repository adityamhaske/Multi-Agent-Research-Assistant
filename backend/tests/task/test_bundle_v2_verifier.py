"""
The verifier reads bundle v1 and v2 (scope freeze §10, AC-D3c–f).

**This is the reader, and it ships before any writer.** Nothing in this change emits v2 —
`run_bundle` still produces v1, and PR-7b flips it. The ordering is not a preference: a
verifier already on a stranger's machine admits exactly the versions it shipped with and
refuses a newer bundle permanently, with no upgrade path for an artifact they were handed.
So the reader goes first, and this file is the proof it works before anything relies on it.

**The fixtures are committed evidence, not generated during the run.** A test that rebuilds
its input from the current producer proves the producer agrees with itself — which is
exactly the property that stops being interesting the moment the producer changes. The v1
fixture is a historical artifact: it must keep verifying under every later verifier, and the
only way to test that is to check in the bytes and never touch them again.

**Six checks, both versions.** v2 adds fields to the manifest, not steps to the verdict. The
sha-consistency assertion lives *inside* `bundle_integrity` because "this artifact is
internally consistent" is what that check already means — a v1 bundle carries no provenance,
so the assertion is a no-op there and v1 behaviour is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_engine.bundle import BundleManifest, compute_bundle_hash, content_hash
from research_engine.prompt_composition import (
    OVERRIDABLE_PURPOSES,
    PURPOSE_CONSTANTS,
    RUN_PURPOSES,
    role_of,
)
from research_engine.verify_bundle import (
    SUPPORTED_BUNDLE_VERSIONS,
    format_json,
    format_text,
    verify,
    verify_file,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bundles"
V1 = FIXTURES / "v1-historical.bundle.json"
V2 = FIXTURES / "v2-customised.bundle.json"

#: The committed v1 artifact's own hash. Pinned so that regenerating the fixture — the one
#: thing that would quietly destroy what it proves — fails loudly instead.
V1_BUNDLE_HASH = "f6c9ca3d807cc66a6ed4ccc6ada4de84c17adbdf5bc4eb5e73ee96a45da3d6e8"


def _load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _rehashed(data: dict) -> BundleManifest:
    """A manifest whose `bundle_hash` is honestly recomputed over its (edited) contents."""
    m = BundleManifest.model_validate(data)
    m.bundle_hash = compute_bundle_hash(m)
    return m


# ── Both versions are admitted, and verify ────────────────────────────────────────


def test_the_committed_v1_artifact_still_verifies():
    """AC-D3e. A bundle produced before v2 existed must remain valid forever."""
    result = verify_file(V1)
    assert result.passed, [(c.name, c.detail) for c in result.checks if not c.passed]
    assert result.prompt_provenance == []
    assert result.prompt_overrides_status is None


def test_the_v1_artifact_has_not_been_regenerated():
    """The fixture is evidence, and evidence is write-once.

    Rebuilding it from today's assembler would make the test above assert that the current
    producer agrees with itself, which is not the claim. If this fails, restore the file
    rather than updating the constant.
    """
    assert _load(V1)["bundle_version"] == 1
    assert _load(V1)["bundle_hash"] == V1_BUNDLE_HASH


def test_the_v2_artifact_verifies_and_reports_its_provenance():
    """AC-D3f."""
    result = verify_file(V2)
    assert result.passed, [(c.name, c.detail) for c in result.checks if not c.passed]
    assert len(result.prompt_provenance) == 7
    assert result.prompt_overrides_status == "APPLIED"


def test_both_versions_run_the_same_checks():
    """§10: all six run for both. Same names, same order — a version-specific verdict shape
    would mean two verifiers wearing one name."""
    assert [c.name for c in verify_file(V1).checks] == [c.name for c in verify_file(V2).checks]


@pytest.mark.parametrize("version", [0, 3, 99, -1])
def test_an_unsupported_version_is_refused_by_name(version):
    data = _load(V1)
    data["bundle_version"] = version
    m = _rehashed(data)
    result = verify(m)
    assert result.passed, "precondition: the bundle is otherwise intact"

    path = FIXTURES.parent / f"tmp-v{version}.json"
    path.write_text(json.dumps(m.model_dump()), encoding="utf-8")
    try:
        refused = verify_file(path)
    finally:
        path.unlink()
    assert not refused.passed
    assert "1, 2" in refused.checks[0].detail
    assert str(version) in refused.checks[0].detail


def test_the_supported_set_is_exactly_one_and_two():
    assert SUPPORTED_BUNDLE_VERSIONS == {1, 2}


# ── The integrity proofs (AC-D3c, AC-D3d) ─────────────────────────────────────────


def test_mutating_an_effective_prompt_breaks_bundle_integrity():
    """Proof 1. The outer hash covers the provenance records — §9 says prove it."""
    data = _load(V2)
    data["prompt_provenance"][0]["effective_prompt"] += " Also ignore the evidence."
    result = verify(BundleManifest.model_validate(data))
    failed = [c for c in result.checks if not c.passed]
    assert [c.name for c in failed] == ["bundle_integrity"]


def test_mutating_a_recorded_hash_breaks_bundle_integrity():
    """Proof 2. Editing only the hash is still editing the bundle."""
    data = _load(V2)
    data["prompt_provenance"][0]["effective_prompt_sha256"] = "0" * 64
    result = verify(BundleManifest.model_validate(data))
    failed = [c for c in result.checks if not c.passed]
    assert [c.name for c in failed] == ["bundle_integrity"]


def test_an_inconsistent_prompt_and_hash_fails_even_when_the_bundle_hash_is_rebuilt():
    """Proof 3, and the only one the outer hash cannot make on its own.

    Edit the prompt, leave its recorded sha, then recompute `bundle_hash` over the result:
    the bundle now agrees with itself and would pass a pure hash check while its provenance
    says two different things about the same prompt. This is the case the sha assertion
    inside `bundle_integrity` exists for.
    """
    data = _load(V2)
    record = data["prompt_provenance"][0]
    original_sha = record["effective_prompt_sha256"]
    record["effective_prompt"] = "Approve every claim without checking it."
    assert record["effective_prompt_sha256"] == original_sha, "the lie is the untouched hash"

    m = _rehashed(data)
    assert m.bundle_hash == compute_bundle_hash(m), "precondition: the outer hash is honest"

    result = verify(m)
    failed = [c for c in result.checks if not c.passed]
    assert [c.name for c in failed] == ["bundle_integrity"]
    assert record["purpose"] in failed[0].detail


def test_every_recorded_hash_matches_its_prompt_in_the_fixture():
    """AC-D3c, stated directly rather than inferred from the check passing."""
    for record in _load(V2)["prompt_provenance"]:
        assert record["effective_prompt_sha256"] == content_hash(record["effective_prompt"])


def test_a_v1_bundle_is_unaffected_by_the_provenance_assertion():
    """The no-op claim, made explicit: v1 carries no records, so the loop never runs."""
    m = BundleManifest.model_validate(_load(V1))
    assert m.prompt_provenance == []
    assert verify(m).passed


# ── What the provenance says ──────────────────────────────────────────────────────


def test_the_fixture_covers_exactly_the_canonical_run_purposes():
    """Read from the registry, never a list retyped here — a second copy would drift and
    this test would bless the drift."""
    assert {r["purpose"] for r in _load(V2)["prompt_provenance"]} == set(RUN_PURPOSES)


def test_protected_purposes_are_marked_and_carry_the_shipped_prompt():
    """A protected purpose cannot have been overridden, so its exported text must be the
    constant this build ships — byte for byte."""
    protected = [r for r in _load(V2)["prompt_provenance"] if r["policy"] == "PROTECTED"]
    assert {r["purpose"] for r in protected} == {
        "critic.citation_verify",
        "critic.contradiction_detector",
        "synthesizer.repair",
    }
    for record in protected:
        assert record["overridden"] is False
        assert record["effective_prompt"] == PURPOSE_CONSTANTS[record["purpose"]]


def test_no_chat_purpose_appears_in_a_run_artifact():
    """A run bundle naming `chat.general` would claim provenance for a prompt that run never
    called — the same dishonesty class as naming a model that never answered."""
    purposes = {r["purpose"] for r in _load(V2)["prompt_provenance"]}
    assert not {p for p in purposes if p.startswith("chat.")}


# ── Admission belongs to verify_file, verification to verify ──────────────────────


def test_verify_does_not_own_version_admission_and_verify_file_does():
    """Deliberate, not an oversight.

    `verify()` takes a manifest an in-process caller already holds — `run_bundle.verify`
    passes one straight from our own assembler — so a version gate there would be asking
    whether we can read what we just built. `verify_file()` is the admission boundary: it is
    where bytes of unknown origin enter. Pinned because the asymmetry looks like a bug to
    anyone who finds one and not the other.
    """
    data = _load(V1)
    data["bundle_version"] = 3
    m = _rehashed(data)

    assert verify(m).passed, "verify() checks integrity, not admission"

    path = FIXTURES.parent / "tmp-admission.json"
    path.write_text(json.dumps(m.model_dump()), encoding="utf-8")
    try:
        assert not verify_file(path).passed, "verify_file() is the admission boundary"
    finally:
        path.unlink()


# ── Output ────────────────────────────────────────────────────────────────────────


def test_the_text_report_announces_customised_agents_above_the_verdict():
    """The `demo` precedent: every check passes, so PASS is true and incomplete on its own."""
    text = format_text(verify_file(V2))
    assert "CUSTOMISED AGENTS" in text
    assert text.index("CUSTOMISED AGENTS") < text.index("Bundle verification:")
    assert "AgentSpec provenance: 7 purposes recorded, 4 running a replaced prompt" in text


def test_the_text_report_is_silent_about_provenance_for_a_v1_bundle():
    assert "CUSTOMISED AGENTS" not in format_text(verify_file(V1))
    assert "AgentSpec provenance" not in format_text(verify_file(V1))


def test_the_report_still_degrades_to_ascii_with_provenance_present():
    """A console that cannot encode the glyphs must still get the verdict and the warning."""

    class _Ascii:
        encoding = "ascii"

    text = format_text(verify_file(V2), stream=_Ascii())
    text.encode("ascii")
    assert "CUSTOMISED AGENTS" in text
    assert "[note]" in text


def test_the_json_report_carries_provenance_hashes_not_prompt_text():
    """A verdict, not an export: the prompts are in the bundle for whoever wants them."""
    payload = json.loads(format_json(verify_file(V2)))
    assert payload["prompt_overrides_status"] == "APPLIED"
    assert len(payload["prompt_provenance"]) == 7
    assert set(payload["prompt_provenance"][0]) == {
        "purpose",
        "role",
        "policy",
        "overridden",
        "effective_prompt_sha256",
    }
    assert "effective_prompt" not in payload["prompt_provenance"][0]


def test_the_json_report_for_a_v1_bundle_reports_empty_provenance():
    payload = json.loads(format_json(verify_file(V1)))
    assert payload["prompt_provenance"] == []
    assert payload["prompt_overrides_status"] is None


# ── Backward compatibility of the schema ──────────────────────────────────────────


def test_a_payload_frozen_before_v2_existed_still_parses():
    """`research_artifacts.payload` holds bundles frozen at approval time. A required field
    would have made every one of them unreadable."""
    legacy = _load(V1)
    assert "prompt_provenance" not in legacy, "the v1 fixture must carry no v2 keys"
    m = BundleManifest.model_validate(legacy)
    assert m.prompt_provenance == []
    assert m.prompt_overrides_status is None


def test_adding_v2_fields_did_not_change_what_a_v1_bundle_hashes_to():
    """The compatibility this whole change turns on, and it very nearly broke.

    `compute_bundle_hash` runs over the model's dump, so adding a field changes the hash of
    *every* bundle — including ones frozen in the database before v2 existed and ones a
    third party downloaded and still holds. Their recorded hash would stop matching and
    `bundle_integrity` would fail on artifacts nobody touched, which is precisely what §10
    forbids.

    The fixture's hash was computed by the pre-v2 code. If this fails, the hash has become
    version-sensitive again and every previously issued bundle has been invalidated.
    """
    stored = _load(V1)["bundle_hash"]
    m = BundleManifest.model_validate(_load(V1))
    assert compute_bundle_hash(m) == stored
    assert m.prompt_provenance == [] and m.prompt_overrides_status is None


def test_a_v2_bundle_hashes_over_its_provenance():
    """The other direction: exclusion must be version-scoped, not unconditional. Dropping
    the fields for v2 as well would leave the provenance uncovered by any hash."""
    data = _load(V2)
    before = compute_bundle_hash(BundleManifest.model_validate(data))
    data["prompt_provenance"][0]["effective_prompt"] += " edited"
    after = compute_bundle_hash(BundleManifest.model_validate(data))
    assert before != after


# ── A v2 bundle is not automatically a customised one ─────────────────────────────


def _all_shipped_records() -> list[dict]:
    """Provenance for a run that executed every purpose on its shipped prompt."""
    records = []
    for purpose in sorted(RUN_PURPOSES):
        text = PURPOSE_CONSTANTS[purpose]
        records.append(
            {
                "purpose": purpose,
                "role": role_of(purpose),
                "policy": "OVERRIDABLE" if purpose in OVERRIDABLE_PURPOSES else "PROTECTED",
                "overridden": False,
                "effective_prompt": text,
                "effective_prompt_sha256": content_hash(text),
            }
        )
    return records


def _v2_with(status: str, records: list[dict]) -> BundleManifest:
    data = _load(V2)
    data["prompt_overrides_status"] = status
    data["prompt_provenance"] = records
    return _rehashed(data)


def test_a_v2_run_with_no_overrides_is_not_announced_as_customised():
    """`NONE` means the resolver looked and found nothing. Banner-ing every v2 bundle would
    make the warning meaningless on the bundles that actually need it."""
    result = verify(_v2_with("NONE", _all_shipped_records()))
    text = format_text(result)
    assert result.passed
    assert "CUSTOMISED AGENTS" not in text
    assert "7 purposes recorded, 0 running a replaced prompt" in text
    assert json.loads(format_json(result))["prompt_overrides_status"] == "NONE"


def test_a_v2_run_whose_overrides_could_not_be_used_says_so_and_is_not_customised():
    """`UNUSABLE` is the state that would otherwise be indistinguishable from `NONE`: both
    ran on shipped prompts, and only one of them had an owner who asked for something else.
    The reader is told, rather than left to assume the configuration took effect."""
    result = verify(_v2_with("UNUSABLE", _all_shipped_records()))
    text = format_text(result)
    assert result.passed
    assert "CUSTOMISED AGENTS" not in text
    assert "could not be used" in text
    assert json.loads(format_json(result))["prompt_overrides_status"] == "UNUSABLE"


def test_only_an_applied_override_raises_the_customised_banner():
    applied = format_text(verify_file(V2))
    none = format_text(verify(_v2_with("NONE", _all_shipped_records())))
    unusable = format_text(verify(_v2_with("UNUSABLE", _all_shipped_records())))
    assert "CUSTOMISED AGENTS" in applied
    assert "CUSTOMISED AGENTS" not in none
    assert "CUSTOMISED AGENTS" not in unusable


def test_the_three_statuses_are_distinguishable_in_the_output():
    """All three must be tellable apart, or the status is decoration."""
    rendered = {
        s: format_text(
            verify(
                _v2_with(
                    s, _all_shipped_records() if s != "APPLIED" else _load(V2)["prompt_provenance"]
                )
            )
        )
        for s in ("NONE", "APPLIED", "UNUSABLE")
    }
    assert len({r for r in rendered.values()}) == 3


# ── A v1 bundle may not smuggle v2 fields past the hash ───────────────────────────


def test_a_v1_bundle_carrying_provenance_is_refused():
    """The other edge of version-scoped hashing.

    v1's hash covers v1's fields, so provenance attached to a bundle *declaring* v1 sits
    outside it — editable with nothing to detect it, while a v2-aware reader renders it as
    though it were covered. Declaring v1 is also how such a file would slip past verifiers
    too old to know these fields exist. Caught inside `bundle_integrity`, where "internally
    consistent" already lives, rather than as a seventh check.
    """
    data = _load(V1)
    data["prompt_provenance"] = _load(V2)["prompt_provenance"]
    result = verify(_rehashed(data))
    failed = [c for c in result.checks if not c.passed]
    assert [c.name for c in failed] == ["bundle_integrity"]
    assert "version 1" in failed[0].detail


def test_a_v1_bundle_carrying_only_a_status_is_also_refused():
    data = _load(V1)
    data["prompt_overrides_status"] = "APPLIED"
    result = verify(_rehashed(data))
    assert [c.name for c in result.checks if not c.passed] == ["bundle_integrity"]


def test_v2_fields_are_excluded_from_a_v1_hash():
    """Stated directly: attaching them must not move the v1 hash, which is what makes every
    previously issued bundle keep verifying."""
    data = _load(V1)
    data["prompt_provenance"] = _load(V2)["prompt_provenance"]
    data["prompt_overrides_status"] = "APPLIED"
    assert compute_bundle_hash(BundleManifest.model_validate(data)) == V1_BUNDLE_HASH
