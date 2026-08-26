"""
Turning a host's response into something comparable across hosts. **Not a test module.**

The parity suite compares *product behaviour*, not storage. A Postgres row and a SQLite
row are allowed to differ; a status code, a state-machine value, an error message and the
set of fields in a response are not. This module draws that line, and it is the only place
it is drawn — a journey that normalized its own observations would be a journey that could
decide what to overlook.

**A value may be redacted; a key never is.** Redaction replaces a volatile *value* with a
token and leaves its key in place, so `==` on two normalized observations still fails when
one host omitted a field entirely. That is the property the whole suite rests on, and
`test_normalize.py` pins it directly.

**Redaction is shape-aware.** A key on the volatile list whose value does not look volatile
is left alone: `app/api/v1/corpus.py::upload_document` returns `id="skip"` when the store
skipped a document, and erasing that by key name would hide a real contract difference
behind a placeholder.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


#: Identity keys, matched structurally rather than listed: `id` itself, or anything ending
#: in `_id`. A hand-written list is always one field behind the schema — `plan_version_id`
#: was missing from the first version of this module, so a raw uuid reached the recorded
#: golden and the server then disagreed with its own recording.
#:
#: Wide matching is safe only because redaction is shape-aware: `model_id` ends in `_id`
#: and holds `claude-haiku-4-5`, which is the contract itself, and `task_id` holds `"1"`.
#: Neither looks like an identity, so neither is touched.
def _is_id_key(key: str) -> bool:
    return key == "id" or key.endswith("_id")


#: Wall-clock, matched structurally for the same reason as identities: `archived_at` and
#: then `generated_at` were each missing from a hand-written list in turn. `_at` is the
#: schema's own convention; `ts` and `timestamp` are the two places it is not used.
#: Present-vs-absent stays meaningful, because only a parsable instant is redacted.
_BARE_TIME_KEYS = frozenset({"ts", "timestamp"})


def _is_time_key(key: str) -> bool:
    return key in _BARE_TIME_KEYS or key.endswith("_at")


#: Wall-clock durations. Nothing can pin these — the same fixture pipeline takes a
#: different number of milliseconds every run — and a difference is a performance
#: observation rather than a behavioural one. Spend is deliberately NOT here; see below.
MEASURE_KEYS = frozenset({"elapsed_seconds", "elapsed_s", "duration_ms"})

#: Spend, token counts and model routing are deliberately ABSENT from every list here.
#: The harness pins the same `MODEL_*` routing and injects the same deterministic embedder
#: on both hosts, so all three are reproducible — and reducing a reproducible value would
#: discard exactly the product-visible state this suite exists to measure. Spend in
#: particular is the number this repository treats as honesty-critical: "$0.00 on one host
#: and $0.003 on the other" is the unmeasured-vs-zero distinction, not noise to round away.
#:
#: If one of them ever does differ between hosts, that is a finding to record in
#: `XFAIL_DIVERGENCES` and fix — never a reason to widen a redaction list.


#: Content digests. A bundle hash covers a document that embeds run, revision and evidence
#: ids, so its value cannot be equal across hosts however deterministic the pipeline is.
#: Presence is still the contract, and each host's own integrity checks — `bundle_integrity`,
#: `report_integrity`, `evidence_integrity` — are what prove its digest is right, so nothing
#: is given up by redacting the value here.
def _is_hash_key(key: str) -> bool:
    return key.endswith("_hash") or key == "evidence_watermark"


_HEX64 = re.compile(r"^[0-9a-f]{64}$", re.I)

#: The pipeline event stream carried in a bundle. Reduced to its presence, on purpose and
#: temporarily: the events come from the `EventSink` port, and the parity harness supplies
#: its own implementation of that port on the server — so comparing the events themselves
#: would compare the test double rather than the product. What is kept is the claim a
#: bundle actually makes, that `trace_available` means a trace is there.
#:
#: Plan Phase 5 gives both hosts one `EventStream`/`EventSink` pairing; when the harness
#: stops substituting, delete this rule and compare the events.
TRACE_KEYS = frozenset({"trace"})

#: Generated prose. Reduced rather than dropped — see `_reduce_text`.
TEXT_KEYS = frozenset({"final_report", "draft_report", "report_markdown", "content", "answer"})

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_MARKER = re.compile(r"\[(\d{1,3})\]")


def _is_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(_UUID.match(value))


def _is_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _reduce_text(value: str) -> dict:
    """A report reduced to what is stable and still worth asserting.

    Comparing the prose would compare the model; dropping the field would hide a host that
    produced no report at all. What survives is whether there is text, and which citation
    markers it carries — the markers being the product's own claim, since every `[n]` is
    supposed to resolve to a numbered source.
    """
    return {"empty": not value.strip(), "markers": sorted({int(m) for m in _MARKER.findall(value)})}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact volatile values, preserving every key and every list order."""
    if key in TRACE_KEYS and isinstance(value, list):
        return {"empty": not value}
    if isinstance(value, dict):
        return {k: normalize(v, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]

    if value is None or key is None:
        return value

    if _is_id_key(key):
        if _is_uuid(value):
            return "<uuid>"
        if isinstance(value, int) and not isinstance(value, bool):
            return "<int-id>"
        return value
    if _is_time_key(key):
        return "<timestamp>" if _is_timestamp(value) else value
    if key in MEASURE_KEYS:
        return "<measure>" if _is_number(value) else value
    if _is_hash_key(key):
        return "<hash>" if isinstance(value, str) and _HEX64.match(value) else value
    if key in TEXT_KEYS:
        return _reduce_text(value) if isinstance(value, str) else value
    return value


def observe(response) -> dict:
    """One host's answer to one request, as the suite compares it.

    A non-JSON body (a Markdown export, a downloaded document) reduces to its media type
    and whether it was empty: the bytes are the engine's output and differ per run, while
    "the desktop served this as `text/plain` and the server as `text/markdown`" is a
    contract difference worth failing on.
    """
    media_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    if media_type == "application/json":
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 — a malformed JSON body is itself an observation
            return {"status": response.status_code, "body": {"malformed_json": True}}
        return {"status": response.status_code, "body": normalize(body)}
    return {
        "status": response.status_code,
        "body": {"media_type": media_type, "empty": not (response.text or "").strip()},
    }
