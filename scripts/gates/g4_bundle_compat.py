#!/usr/bin/env python3
"""
Gate G-4: a 3.1 bundle verifies under the unchanged v3.0.2 verifier, and tampering is caught
(internal/rfcs/V3.1-corpus-scope.md §14.1, D-20; release blocker 3).

For each bundle given, three things are checked, with both verifiers:
- **the v3.0.2 verifier**, unpacked byte-for-byte from the `v3.0.2` tag with `git archive`
  and run in its own interpreter. The sha256 of its `verify_bundle.py` is recorded;
- **this checkout's verifier**, run the same way;
- the cases.

| Case | Expected |
|---|---|
| The bundle as produced | both pass |
| A source edited | both fail `bundle_integrity` |
| The `corpus_selection` trace entry edited | both fail `bundle_integrity` |
| The `grounding_validation` trace entry edited | both fail `bundle_integrity` |
| The report edited | both fail `report_integrity` and `bundle_integrity` |
| The selection rewritten so its cited sources fall outside it, `bundle_hash` recomputed | 3.1 fails **only** `corpus_selection`; v3.0.2 passes |

A bundle with no `corpus_selection` entry is refused: G-4 is about selected-files runs, and
proving the old verifier accepts a bundle without one says nothing about them. A
`grounding_validation` case is skipped, and the skip recorded, only when the bundle has no
such entry.

    python scripts/gates/g4_bundle_compat.py BUNDLE.json [...] \\
        --out release-audit/v3.1.0/evidence/G-4

Exit 0 only when every expectation holds; the evidence JSON names the build that ran it, each
bundle's `bundle_hash` and sha256, and every verdict with its checks.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TAG = "v3.0.2"

#: Runs one verifier against one bundle file in a fresh interpreter whose only
#: `research_engine` is the one at `engine`, and prints the verdict as JSON.
PROBE = """
import json, sys
sys.path.insert(0, {engine!r})
from research_engine import verify_bundle
assert verify_bundle.__file__.startswith({engine!r}), verify_bundle.__file__
r = verify_bundle.verify_file({path!r})
print(json.dumps({{"passed": r.passed, "checks": {{c.name: c.passed for c in r.checks}}}}))
"""


class GateFailed(Exception):
    pass


def released_verifier(scratch: Path) -> tuple[Path, str]:
    """The v3.0.2 engine package, from the tag; returns its import root and the verifier's sha."""
    done = subprocess.run(
        ["git", "archive", "--format=tar", TAG, "backend/research_engine"],
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    if done.returncode != 0:
        raise GateFailed(f"cannot read the {TAG} tag: {done.stderr.decode()[:300]}")
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        tar.extractall(scratch, filter="data")
    engine = scratch / "backend"
    digest = hashlib.sha256(
        (engine / "research_engine" / "verify_bundle.py").read_bytes()
    )
    return engine, digest.hexdigest()


def verdict(engine: Path, bundle: dict, scratch: Path, name: str) -> dict:
    path = scratch / f"{name}.bundle.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", PROBE.format(engine=str(engine), path=str(path))],
        capture_output=True,
        text=True,
        cwd=scratch,
        check=False,
    )
    if done.returncode != 0:
        raise GateFailed(
            f"the verifier at {engine} crashed on {name}:\n{done.stderr[-1500:]}"
        )
    return json.loads(done.stdout.strip().splitlines()[-1])


def _trace_entry(bundle: dict, event: str) -> dict | None:
    return next((t for t in bundle.get("trace", []) if t.get("event") == event), None)


def tampered(bundle: dict) -> dict[str, dict | None]:
    """Each edit the gate names, applied to a copy. `None` where the bundle has nothing to edit."""
    out: dict[str, dict | None] = {}

    b = copy.deepcopy(bundle)
    b["sources"][0]["title"] = str(b["sources"][0].get("title") or "") + " (edited)"
    out["source edited"] = b

    b = copy.deepcopy(bundle)
    entry = _trace_entry(b, "corpus_selection")
    entry["resolved"].append({"document_id": "an-unselected-document", "doc_key": "x"})
    out["selection trace entry edited"] = b

    b = copy.deepcopy(bundle)
    entry = _trace_entry(b, "grounding_validation")
    if entry is None:
        out["grounding_validation edited"] = None
    else:
        entry["claims_rejected"] = int(entry.get("claims_rejected") or 0) + 1
        out["grounding_validation edited"] = b

    b = copy.deepcopy(bundle)
    b["report"] = b["report"] + "\nAn unsupported sentence added after approval.\n"
    out["report edited"] = b
    return out


def outside_selection_rehashed(bundle: dict) -> dict:
    """The selection rewritten so the cited documents fall outside it, then `bundle_hash`
    recomputed. Sources, evidence and claims are untouched, so the bundle is consistent in
    every other respect, and only the 3.1 `corpus_selection` check can object. Editing a
    source's URL instead would also break `claim_evidence_linkage`, which names that URL,
    and so would not show what the selection check alone catches."""
    sys.path.insert(0, str(BACKEND))
    from research_engine.bundle import BundleManifest, compute_bundle_hash

    b = copy.deepcopy(bundle)
    cited = {
        str(s.get("url", ""))[len("corpus://") :].split("#", 1)[0]
        for s in b["sources"]
        if str(s.get("url", "")).startswith("corpus://")
    }
    if not cited:
        raise GateFailed(
            "the bundle cites no corpus source to put outside its selection"
        )
    entry = _trace_entry(b, "corpus_selection")
    entry["resolved"] = [
        item for item in entry["resolved"] if str(item.get("document_id")) not in cited
    ] or [{"document_id": "an-unrelated-document", "doc_key": "unrelated"}]
    b["bundle_hash"] = compute_bundle_hash(BundleManifest.model_validate(b))
    return b


EXPECTED_FAILURES = {
    "source edited": {"bundle_integrity"},
    "selection trace entry edited": {"bundle_integrity"},
    "grounding_validation edited": {"bundle_integrity"},
    "report edited": {"report_integrity", "bundle_integrity"},
}


def check_bundle(path: Path, old: Path, new: Path, scratch: Path) -> dict:
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if _trace_entry(bundle, "corpus_selection") is None:
        raise GateFailed(
            f"{path} records no corpus_selection: not a selected-files run's bundle"
        )
    record: dict = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bundle_hash": bundle.get("bundle_hash"),
        "bundle_version": bundle.get("bundle_version"),
        "demo": bundle.get("demo"),
        "cases": {},
    }
    problems: list[str] = []

    def run_case(name: str, b: dict, expect) -> None:
        verdicts = {
            "v3.0.2": verdict(
                old, b, scratch, f"{path.stem}-{name}-old".replace(" ", "_")
            ),
            "3.1": verdict(
                new, b, scratch, f"{path.stem}-{name}-new".replace(" ", "_")
            ),
        }
        held = expect(verdicts)
        record["cases"][name] = {**verdicts, "held": held}
        if not held:
            problems.append(f"{path.name}: {name}: {verdicts}")

    run_case(
        "as produced", bundle, lambda v: v["v3.0.2"]["passed"] and v["3.1"]["passed"]
    )
    for name, b in tampered(bundle).items():
        if b is None:
            record["cases"][name] = {
                "skipped": "the bundle records no grounding_validation"
            }
            continue
        want = EXPECTED_FAILURES[name]

        def failed_on(v, want=want):
            return all(
                not v[k]["passed"]
                and want <= {c for c, ok in v[k]["checks"].items() if not ok}
                for k in ("v3.0.2", "3.1")
            )

        run_case(name, b, failed_on)

    def only_selection(v):
        failed = {c for c, ok in v["3.1"]["checks"].items() if not ok}
        # 3.0.2 has no selection check, so it must accept what is otherwise a sound bundle:
        # the new check is an addition, not a format change (RFC V3.1 §8.6).
        return failed == {"corpus_selection"} and v["v3.0.2"]["passed"]

    run_case(
        "outside selection, rehashed",
        outside_selection_rehashed(bundle),
        only_selection,
    )
    record["problems"] = problems
    return record


def _build() -> dict:
    sys.path.insert(0, str(BACKEND))
    from research_engine.build_info import build_info

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    return {**build_info().as_dict(), "checkout": head.stdout.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("bundles", nargs="+", type=Path)
    parser.add_argument(
        "--out", type=Path, help="evidence directory (writes g4.json there)"
    )
    args = parser.parse_args(argv)

    evidence: dict = {
        "gate": "G-4",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "build": _build(),
        "python": sys.version,
    }
    with tempfile.TemporaryDirectory(prefix="g4-") as tmp:
        scratch = Path(tmp)
        try:
            old, old_sha = released_verifier(scratch / "released")
            evidence["v3.0.2_verifier"] = {
                "tag": TAG,
                "verify_bundle.py sha256": old_sha,
            }
            evidence["bundles"] = [
                check_bundle(p, old, BACKEND, scratch) for p in args.bundles
            ]
            problems = [p for b in evidence["bundles"] for p in b["problems"]]
            evidence["result"] = "FAIL" if problems else "PASS"
        except GateFailed as exc:
            evidence["result"], problems = "FAIL", [str(exc)]
    evidence["problems"] = problems
    text = json.dumps(evidence, indent=2) + "\n"
    print(text)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "g4.json").write_text(text, encoding="utf-8")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
