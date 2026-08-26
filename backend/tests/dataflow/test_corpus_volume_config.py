"""
Corpus persistence across containers (docs/12 M10, AGENTS.md "two hosts, one contract").

`app/config.py::corpus_path` resolves to `/app/data/corpus` inside the image. `api` and
`worker` are separate containers with separate writable layers — a document uploaded
through `api` and never visible to `worker` is exactly the "corpus database not found"
failure `pipeline_runner.py` guards against, and neither container's writable layer
survives a `docker compose down` / `up --build` recreate at all.

These tests parse `docker-compose.full.yml` directly rather than asserting behaviour
against a running stack (that check is manual — see docs/deployment/09-docker.md). What
they pin is the configuration shape that makes the shared, durable volume actually take
effect: the same named volume, mounted at the same path, on both services, and declared
at top level so `docker compose down` (without `-v`) can never delete it as a side effect
of removing an anonymous volume.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

COMPOSE_PATH = Path(__file__).resolve().parents[3] / "docker-compose.full.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _corpus_volume_mounts(compose: dict, service: str) -> list[str]:
    """This service's `volumes:` entries that mount into /app/data."""
    volumes = compose["services"][service].get("volumes") or []
    return [v for v in volumes if isinstance(v, str) and v.endswith(":/app/data")]


def test_api_and_worker_mount_the_same_named_corpus_volume(compose: dict):
    api_mounts = _corpus_volume_mounts(compose, "api")
    worker_mounts = _corpus_volume_mounts(compose, "worker")

    assert api_mounts, "api must mount a volume at /app/data — corpus_path resolves there"
    assert worker_mounts, "worker must mount a volume at /app/data — same reason"
    assert api_mounts == worker_mounts, (
        "api and worker must mount the SAME volume at /app/data, or a document uploaded "
        "through one is invisible to the other (the split-brain bug AGENTS.md records)"
    )

    volume_name = api_mounts[0].split(":", 1)[0]
    assert volume_name in compose["volumes"], (
        f"{volume_name!r} must be declared under the top-level `volumes:` key, or it is "
        "an anonymous volume tied to the container and not the durable store this exists "
        "to provide"
    )


def test_corpus_volume_is_not_bind_mounted_from_a_relative_path(compose: dict):
    """A relative bind mount (`./data:/app/data`) would resolve against wherever compose
    is invoked from — the exact class of bug `corpus_path` exists to avoid one layer down
    (app/config.py). The volume must be a named Docker volume, not a host path."""
    api_mounts = _corpus_volume_mounts(compose, "api")
    volume_name = api_mounts[0].split(":", 1)[0]
    assert not volume_name.startswith((".", "/")), (
        f"corpus volume source {volume_name!r} looks like a bind-mounted path, not a named volume"
    )
