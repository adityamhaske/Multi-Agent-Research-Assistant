"""
The bundle hash as `docs/reference/15-bundle-format.md` publishes it, implemented from the prose.

A third party checking a bundle does not run this repository's `compute_bundle_hash`; they
read the format document and implement what it says. So the document is a contract in its
own right, and the only way to know it is correct is to implement it independently and run it
against real bundles. Calling `compute_bundle_hash` here would prove the code agrees with
itself, which is not the question.

**The defect this pins.** Until bundle v2 the document said the hash covers every field but
`bundle_hash`. That stopped being true for v1 once the v2 fields joined the schema: a v1
bundle from a current producer — every session bundle — serialises `prompt_provenance: []`
and `prompt_overrides_status: null`, which its hash excludes. A reader following the old text
computed a different digest and would conclude that every such bundle had been tampered with.
`test_a_current_v1_bundle_fails_the_pre_v2_procedure` keeps that failure on record.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_engine import bundle as bundle_mod
from research_engine.bundle import BundleManifest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bundles"

#: docs/15 "Fields by version", transcribed from the document — deliberately not imported from
#: `research_engine.bundle`, which is the implementation under test.
V1_FIELDS = frozenset(
    {
        "bundle_version",
        "session_id",
        "query",
        "research_depth",
        "demo",
        "report",
        "report_hash",
        "claims",
        "evidence",
        "sources",
        "contradictions",
        "models",
        "cost_usd",
        "tokens_input",
        "tokens_output",
        "elapsed_seconds",
        "approval_chain",
        "trace",
        "trace_available",
        "created_at",
        "bundle_hash",
    }
)
V2_FIELDS = V1_FIELDS | {"prompt_provenance", "prompt_overrides_status"}
FIELDS_BY_VERSION = {1: V1_FIELDS, 2: V2_FIELDS}


def documented_hash(bundle: dict) -> str:
    """docs/15, "`bundle_hash` scope", step by step."""
    # 1. Keep only the fields the declared version defines.
    defined = FIELDS_BY_VERSION[bundle["bundle_version"]]
    d = {k: v for k, v in bundle.items() if k in defined}
    # 2. Blank `bundle_hash`.
    d["bundle_hash"] = ""
    # 3. Canonical JSON: sorted keys, non-ASCII kept as is, no whitespace.
    canonical = json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    # 4. SHA-256 of the UTF-8 encoding.
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Non-ASCII on purpose: step 3 keeps it unescaped, and an implementation that escaped it
# would hash different bytes.
REPORT = "# Café findings\n\nThe claim holds — per the source [1].\n\n## Sources\n\n[1] https://example.org/a\n"


def _fresh(prompt_provenance: list[dict] | None) -> dict:
    """A bundle exactly as a reader receives it: assembled, serialised, parsed back."""
    manifest = bundle_mod.assemble(
        session_id="00000000-0000-0000-0000-000000000009",
        query="Does the claim hold?",
        report=REPORT,
        evidence=[
            {
                "source_url": "https://example.org/a",
                "source_title": "A",
                "snippet": "The claim holds, according to this page.",
                "key_fact": "holds",
            }
        ],
        sources=[{"index": 1, "url": "https://example.org/a", "title": "A", "snippet": ""}],
        models={"planner": "fake:planner"},
        approval_chain=[
            {
                "action": "approved",
                "draft_hash": _sha256(REPORT),
                "timestamp": "2026-09-24T00:00:00+00:00",
            }
        ],
        prompt_provenance=prompt_provenance,
        prompt_overrides_status="APPLIED" if prompt_provenance else None,
    )
    return json.loads(bundle_mod.serialize(manifest))


PROMPT = "Plan in at most three tasks — primary sources first."
PROVENANCE = [
    {
        "purpose": "planner.main",
        "role": "planner",
        "policy": "OVERRIDABLE",
        "overridden": True,
        "effective_prompt": PROMPT,
        "effective_prompt_sha256": _sha256(PROMPT),
    }
]


def _bundles():
    return {
        "historical v1 fixture": json.loads(
            (FIXTURES / "v1-historical.bundle.json").read_text("utf-8")
        ),
        "v2 fixture": json.loads((FIXTURES / "v2-customised.bundle.json").read_text("utf-8")),
        "freshly assembled v1": _fresh(None),
        "freshly assembled v2": _fresh(PROVENANCE),
    }


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("historical v1 fixture", 1),
        ("v2 fixture", 2),
        ("freshly assembled v1", 1),
        ("freshly assembled v2", 2),
    ],
)
def test_the_documented_procedure_reproduces_the_recorded_hash(name, version):
    bundle = _bundles()[name]
    assert bundle["bundle_version"] == version
    assert documented_hash(bundle) == bundle["bundle_hash"], name


def test_a_current_v1_bundle_fails_the_pre_v2_procedure():
    """The regression: the procedure docs/15 published before v2 rejects a bundle issued today."""
    bundle = _fresh(None)
    assert bundle["bundle_version"] == 1
    # Why: the current schema serialises the v2 fields on a v1 bundle, empty.
    assert bundle["prompt_provenance"] == []
    assert bundle["prompt_overrides_status"] is None

    old = dict(bundle, bundle_hash="")
    old_digest = _sha256(json.dumps(old, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    assert old_digest != bundle["bundle_hash"]
    assert documented_hash(bundle) == bundle["bundle_hash"]


def test_the_documented_v1_fields_are_what_a_pre_v2_bundle_carries():
    """Checked against a bundle issued before v2 existed, not against the current schema."""
    historical = json.loads((FIXTURES / "v1-historical.bundle.json").read_text("utf-8"))
    assert set(historical) == V1_FIELDS


def test_the_documented_v2_fields_are_the_whole_current_schema():
    """A field added to the manifest and not to the docs table would sit outside every
    documented hash, and a reader implementing the document would reject every bundle."""
    assert set(BundleManifest.model_fields) == V2_FIELDS
