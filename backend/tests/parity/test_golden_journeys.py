"""
Golden behavioural parity: the same product journey, driven against both hosts.

**What this is not.** It is not a comparison of the two implementations against each
other. Two implementations that agree can both be wrong, and this repository has already
shipped that exact test once — `test_desktop_contract_gaps` called the desktop's corpus
routes and asserted the two desktop response shapes matched, which proved the bug was
consistent rather than that it was correct (`AGENTS.md`, "Registration is not behaviour").

So every step is compared to a **third thing**: a golden recorded once and reviewed by a
human. Both hosts are asserted against it. A shared defect fails both; a divergence names
which host moved.

And agreement is not enough on its own. Two hosts that both return nothing agree
perfectly, so each journey also declares product facts that must hold — see
`tests/parity/liveness.py`. A journey whose steps are all empty fails on both hosts even
when they match each other and match the golden.

**Regenerating.** `PARITY_RECORD=1 python -m pytest tests/parity -k golden` rewrites
`golden/*.json` from the SERVER host, which is the reference. Never regenerate to make a
red test green — read the diff first, because a diff is either a contract change you meant
or the defect the suite exists to catch.

**Known divergences are recorded, not fixed.** `XFAIL_DIVERGENCES` names each one with the
plan phase that closes it. A milestone that both records a contract and repairs it cannot
show which of its assertions were load-bearing, so Phase 0 only records.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.parity import journeys
from tests.parity.drivers import desktop_driver, server_driver
from tests.parity.liveness import at_least_one_nonempty_body, failing_checks

GOLDEN_DIR = Path(__file__).parent / "golden"
RECORDING = os.environ.get("PARITY_RECORD") == "1"

#: Steps where the two hosts are known to disagree today, each with the phase that closes
#: it. A step named here is asserted to STILL diverge, so a fix that lands without deleting
#: its entry fails the suite and the list can only shrink.
XFAIL_DIVERGENCES: dict[str, str] = {
    # ── Identity. Not a defect and not a shape problem: the desktop host IS one local
    # user with a fixed sentinel address and display name (docs/13 §7). Phase 1 closed the
    # field-omission half — `is_active`, every `api_key_*`, `connection_verdict` and the
    # whole `preferences` object are present now — and what remains is the identity itself.
    "identity-and-models/who am I": (
        "plan phase 10 — the desktop is a single local user, so email and display_name are "
        "fixed sentinels. Reclassify as a capability difference rather than a divergence"
    ),
    # ── Was two unrelated things in one response. One of them is now closed.
    #
    # The preset half — "the server enriches presets.ollama from installed models and the
    # desktop returns the static table", the real divergence this suite found — was fixed
    # in plan phase 8: the desktop calls `_ollama_presets_from_installed()` too, so it can
    # no longer offer a local model the machine never pulled. `presets` is now byte-identical
    # on both hosts, which is checkable here rather than asserted, because
    # `drivers.pin_local_llm_probe` gives both the same installed-model list.
    "identity-and-models/the model catalog": (
        "by design — `available_providers` and the per-model `available` flag differ "
        "because each host answers from where its own keys live: the server from settings "
        "(the harness pins them, see drivers._PINNED_KEYS) and the desktop from the "
        "keychain, which in `fake=True` holds nothing, so it reports []. Not a gap and not "
        "harness drift — the same BYOK-vs-keychain split that made `GET /models` one of "
        "the five routes MODELS_DIVERGENT keeps per host; reclassified in plan phase 8, "
        "which closed the preset half of this entry"
    ),
    # §2.5 #2 is gone: Phase 1 filled the body fields by declaring the model, and Phase 2b
    # made the status codes, the failure mapping, the download's Content-Type and the
    # body-less 204 one contract in `app/services/corpus_ingest.py`.
    # ── First-launch state.
    "projects/list projects": (
        "plan phase 8 — the desktop seeds a General project at launch and the server "
        "creates one lazily, so a fresh install lists one project on desktop and zero "
        "on the server"
    ),
}


def _golden_path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.json"


def _load_golden(name: str) -> dict[str, dict]:
    path = _golden_path(name)
    if not path.exists():
        pytest.fail(
            f"no golden for journey {name!r}. Record one with "
            "`PARITY_RECORD=1 python -m pytest tests/parity -k golden`, then read the diff "
            "before committing it."
        )
    return {step["step"]: step for step in json.loads(path.read_text())}


async def _observe(journey, driver):
    unmet = journeys.unmet_requirements(journey, driver)
    if unmet:
        pytest.skip(f"{driver.name} cannot run {journey.name}: {'; '.join(unmet)}")
    return await journeys.drive(journey, driver)


@pytest.mark.parametrize("journey", journeys.ALL, ids=lambda j: j.name)
async def test_the_server_matches_the_recorded_contract(journey, tmp_path):
    async with server_driver(tmp_path / "server") as driver:
        observed = await _observe(journey, driver)
    if RECORDING:
        _golden_path(journey.name).write_text(json.dumps(observed, indent=2) + "\n")
        pytest.skip(f"recorded {len(observed)} steps for {journey.name}")
    _assert_journey(journey, observed, host="server")


@pytest.mark.parametrize("journey", journeys.ALL, ids=lambda j: j.name)
async def test_the_desktop_matches_the_recorded_contract(journey, tmp_path):
    async with desktop_driver(tmp_path / "desktop") as driver:
        observed = await _observe(journey, driver)
    if RECORDING:
        pytest.skip("the server is the reference host; recording from the desktop is refused")
    _assert_journey(journey, observed, host="desktop")


def _assert_journey(journey, observed: list[dict], *, host: str) -> None:
    _assert_alive(journey, observed, host=host)
    _assert_against_golden(journey.name, observed, host=host)


def _assert_alive(journey, observed: list[dict], *, host: str) -> None:
    """Before comparing anything: did this journey actually do something on this host?

    Run first, so a host that produced nothing fails with "nothing happened" rather than
    with a shape mismatch that sends the reader looking in the wrong place.
    """
    assert at_least_one_nonempty_body(observed), (
        f"{host} completed {journey.name} without a single successful non-empty response — "
        "the journey passed by doing nothing, which is not parity"
    )
    failed = failing_checks(journey, observed)
    assert not failed, f"{host} broke these product facts in {journey.name}:\n  " + "\n  ".join(
        failed
    )


def _assert_against_golden(name: str, observed: list[dict], *, host: str) -> None:
    golden = _load_golden(name)
    seen = {step["step"] for step in observed}

    missing = set(golden) - seen
    assert not missing, f"{host} never reached these recorded steps of {name}: {sorted(missing)}"
    extra = seen - set(golden)
    assert not extra, (
        f"{host} produced steps the golden does not record: {sorted(extra)} — "
        "re-record if the journey genuinely gained a step"
    )

    diverged: list[str] = []
    for step in observed:
        key = f"{name}/{step['step']}"
        want = {k: v for k, v in golden[step["step"]].items() if k != "step"}
        got = {k: v for k, v in step.items() if k != "step"}
        if got == want:
            assert key not in XFAIL_DIVERGENCES or host == "server", (
                f"{key} no longer diverges on {host} — delete its XFAIL_DIVERGENCES entry"
            )
            continue
        if key in XFAIL_DIVERGENCES and host == "desktop":
            continue
        diverged.append(f"  {key}\n    golden: {want}\n    {host}: {got}")

    assert not diverged, f"{host} diverges from the recorded contract:\n" + "\n".join(diverged)


# ── Guards on the harness itself ──────────────────────────────────────────────────


@pytest.mark.parametrize("journey", journeys.ALL, ids=lambda j: j.name)
def test_every_journey_declares_product_facts(journey):
    """A journey with no checks records shapes and asserts nothing about meaning."""
    assert journey.checks, (
        f"{journey.name} declares no checks — add at least one product fact, or the journey "
        "passes whenever both hosts agree, including on doing nothing"
    )


@pytest.mark.parametrize("journey", journeys.ALL, ids=lambda j: j.name)
def test_no_golden_is_degenerate(journey):
    """The recorded contract itself must not be a page of empty results.

    Checked against the committed file rather than a live run: a golden recorded from a
    broken host would otherwise become the contract, and every later run would agree with
    it forever.
    """
    path = _golden_path(journey.name)
    if not path.exists():
        pytest.skip(f"{journey.name} has no golden yet")
    recorded = json.loads(path.read_text())
    assert recorded, f"the golden for {journey.name} records no steps at all"
    assert at_least_one_nonempty_body(recorded), (
        f"the golden for {journey.name} contains no successful non-empty response — it was "
        "recorded from a host that did nothing, and would make every future run agree with "
        "a broken baseline"
    )


def test_every_recorded_divergence_names_a_plan_phase():
    """The same anti-rot rule `test_host_parity` applies to its own tables."""
    for step, reason in XFAIL_DIVERGENCES.items():
        assert "phase" in reason.lower() and len(reason) > 20, (
            f"{step} needs a reason naming the phase that closes it, not {reason!r}"
        )
