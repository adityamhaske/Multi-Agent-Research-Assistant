"""
Reading a LangGraph checkpoint with the distinction the production helper cannot express.

`app.services.checkpoints.get_thread_state` returns `snapshot.values if snapshot else {}`, so
a **missing** checkpoint and an **empty** one are indistinguishable. Three outcomes, never
merged:

    READ        a snapshot was decoded — its evidence may still be empty, which is a
                *finding*, not a failure
    MISSING     no snapshot for this thread_id
    UNREADABLE  a snapshot exists and could not be decoded into a checkpoint

"empty" is not one of these: emptiness is a property of what was read, and only a READ
outcome can report it.

**Lives in the engine because it is pure** — a saver protocol, `enum`, `dataclass`, nothing
else. Two callers need it: `migration/` (which is why it was written) and `app/run_execution`,
which reads the final state of a native run to persist its evidence. A copy in each would be
the same second-home shape this repository keeps paying for. `migration/checkpoint.py`
re-exports these names.

**A decode that does not raise is not a decode that succeeded.** Corrupting a real saver's
stored blob produces a value that still deserialises — to the integer `0` — so the shape is
checked, not merely the absence of an exception. That defect shipped once and reintroduced the
collapse one level below where it had been fixed.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class CheckpointOutcome(enum.StrEnum):
    READ = "READ"
    MISSING = "MISSING"
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class CheckpointRead:
    outcome: CheckpointOutcome
    values: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def evidence(self) -> list[dict]:
        """Only meaningful when READ. Empty on MISSING/UNREADABLE — and the caller must
        branch on `outcome` before reading this, or it reintroduces the collapse."""
        return list(self.values.get("evidence") or [])

    @property
    def contradictions(self) -> list[dict]:
        return list(self.values.get("contradictions") or [])


async def read_checkpoint(saver, thread_id: str) -> CheckpointRead:
    """Read one thread's latest state, distinguishing all three outcomes.

    Uses `aget_tuple` rather than `graph.aget_state`: the graph wrapper normalises a
    missing snapshot into an empty-values StateSnapshot, which is the collapse again one
    level up. `aget_tuple` returns `None` for "no such thread", unambiguously.
    """
    try:
        tup = await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
    except Exception as exc:  # noqa: BLE001 — decode/IO failure is a distinct outcome
        return CheckpointRead(
            CheckpointOutcome.UNREADABLE, error=f"{type(exc).__name__}: {exc}"[:400]
        )

    if tup is None:
        return CheckpointRead(CheckpointOutcome.MISSING)

    # A decode that does not raise is not a decode that succeeded.
    #
    # Found by a dry run against a deliberately corrupted saver's stored blob: the byte
    # sequence still deserialises — to the integer `0` — and the previous
    # `(tup.checkpoint or {}).get("channel_values") or {}` turned that into an empty dict
    # and reported READ. A corrupt checkpoint was therefore indistinguishable from a run
    # that genuinely gathered nothing, which is precisely the collapse this module exists
    # to prevent, reintroduced one level below where it was fixed.
    #
    # So the shape is checked, not just the absence of an exception. `channel_values`
    # missing entirely is UNREADABLE rather than empty for the same reason: "a format this
    # code does not understand" is not "a run with no evidence".
    raw = tup.checkpoint
    if not isinstance(raw, Mapping):
        return CheckpointRead(
            CheckpointOutcome.UNREADABLE,
            error=f"checkpoint decoded to {type(raw).__name__}, not a mapping",
        )
    channels = raw.get("channel_values")
    if channels is None:
        return CheckpointRead(
            CheckpointOutcome.UNREADABLE, error="checkpoint carries no channel_values"
        )
    if not isinstance(channels, Mapping):
        return CheckpointRead(
            CheckpointOutcome.UNREADABLE,
            error=f"channel_values is {type(channels).__name__}, not a mapping",
        )

    try:
        values = dict(channels)
    except Exception as exc:  # noqa: BLE001 — a snapshot that will not unpack
        return CheckpointRead(
            CheckpointOutcome.UNREADABLE, error=f"{type(exc).__name__}: {exc}"[:400]
        )

    return CheckpointRead(CheckpointOutcome.READ, values=values)
