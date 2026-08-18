"""
The tri-state checkpoint reader, re-exported.

It moved to `research_engine/checkpoint_read.py` when the V2-native runtime needed it too:
the module is pure — a saver protocol and two small types — and a copy in `app/` and one in
`migration/` would be two homes for the one rule this milestone exists to protect. Every
`from migration.checkpoint import ...` in the tool still works, and there is one definition.
"""

from __future__ import annotations

from research_engine.checkpoint_read import CheckpointOutcome, CheckpointRead, read_checkpoint

__all__ = ["CheckpointOutcome", "CheckpointRead", "read_checkpoint"]
