"""
The desktop's corpus layout: one corpus file per project, and the one-time move off the
shared store every desktop release before 3.1 used.

**Why this exists.** Up to 3.0.x the desktop kept one `corpus.sqlite` for the whole app and
its locator ignored `project_id`, so every project listed, searched, chatted over and cited
every other project's documents, and deleting a project left its documents behind
(internal/rfcs/V3.1-corpus-scope.md B-1). From 3.1 the desktop uses the server's layout —
`corpus_<project_id>.sqlite` — so isolation is a property of which file is opened, not of a
filter someone has to remember.

**The move (RFC §7.3, D-17).** The shared store does not record which project owned each
document, so its documents cannot be returned to their projects. They move, all together, to
one new project, "Documents from before 3.1". Nothing is copied into any other project.

Ownership has exactly one authority point: the `corpus_layout` row of the desktop-only
`app_meta` table in `desktop.sqlite`. The locator opens only the stores that value names —
`shared` opens `corpus.sqlite` for every project, `per_project` opens only per-project files —
so there is never an instant at which two writable stores can diverge. The commit that sets
`per_project` is the moment the new project becomes authoritative. The move runs during
startup, before the HTTP server accepts a request, so no upload, delete or run can touch
either store while it happens.

Every step is re-entrant and the backup is never deleted: a crash at any point is completed
or rolled back by the next launch (see `migrate_legacy_corpus` for the state table).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import select, text

from research_engine.corpus import CorpusStore
from research_engine.embeddings import FakeEmbeddings, LocalEmbeddings

logger = structlog.get_logger()

CORPUS_DIRNAME = "corpus"
LEGACY_FILENAME = "corpus.sqlite"
BACKUP_FILENAME = "corpus.legacy-3.0.sqlite"
LOCK_FILENAME = "corpus.migration.lock"
LEGACY_PROJECT_NAME = "Documents from before 3.1"
LEGACY_PROJECT_NOTE = (
    "Your documents from before 3.1 were moved here. Projects no longer share documents: "
    "to use a document in another project, upload it there."
)

LAYOUT_KEY = "corpus_layout"
MIGRATION_KEY = "corpus_legacy_migration"
SHARED, PER_PROJECT = "shared", "per_project"

_SQLITE_SIDECARS = ("", "-wal", "-shm")


def default_embedder(*, fake: bool = False):
    """The desktop's corpus embedder: local Ollama, the same `ollama:<model>` id scheme as
    the server so a corpus indexed on one host reads as the same model on the other.

    Under `--fake`, the in-process deterministic one, as `app.adapters.embeddings_for` gives
    the server under `llm_mode="fake"`. A scripted run must reach no model, and without this
    one on a machine with no Ollama could not ingest a single file."""
    if fake:
        return FakeEmbeddings()
    return LocalEmbeddings(
        model=os.environ.get("CORPUS_EMBEDDINGS_MODEL", "nomic-embed-text"),
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    )


class DesktopCorpusLocator:
    """`CorpusLocator` for the desktop, honouring the layout `app_meta` records.

    One embedder for every store, so a document indexed through one store and searched
    through another is embedded by the same model instance. Tests replace `embedder`.
    """

    def __init__(self, data_dir: str | Path, layout: str = PER_PROJECT, *, fake: bool = False):
        self._data_dir = Path(data_dir)
        self.layout = layout
        self.embedder = default_embedder(fake=fake)

    def path_for(self, project_id) -> Path:
        if self.layout == SHARED:
            return self._data_dir / LEGACY_FILENAME
        return self._data_dir / CORPUS_DIRNAME / f"corpus_{project_id}.sqlite"

    def open_existing(self, project_id) -> CorpusStore | None:
        """This project's store if it has one — synchronous, for chat's store factory."""
        path = self.path_for(project_id)
        return CorpusStore(path, self.embedder) if path.exists() else None

    async def for_project(self, project_id, *, keys=None):  # noqa: ARG002
        return self.open_existing(project_id)

    async def ensure(self, project_id, *, keys=None):  # noqa: ARG002
        path = self.path_for(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        return CorpusStore(path, self.embedder)

    def paths_to_delete(self, project_id) -> list[Path]:
        if self.layout == SHARED:
            # The shared store belongs to every project; deleting one must not remove it.
            return []
        base = self.path_for(project_id)
        return [base.with_name(base.name + suffix) for suffix in _SQLITE_SIDECARS]

    def delete(self, project_id) -> None:
        for path in self.paths_to_delete(project_id):
            try:
                path.unlink(missing_ok=True)
            except OSError as e:  # noqa: PERF203
                logger.warning("corpus_cleanup_failed", project_id=str(project_id), error=str(e))


# ── The move ──────────────────────────────────────────────────────────────────────


class MigrationRefused(RuntimeError):
    """A check failed. The shared layout stays in force and nothing was lost."""


def _backup(src: Path, dst: Path) -> None:
    """Copy a SQLite database, WAL included, through SQLite's online backup API."""
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with contextlib.closing(sqlite3.connect(src)) as source:
        with contextlib.closing(sqlite3.connect(tmp)) as target:
            source.backup(target)
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, dst)


def _fingerprint(path: Path) -> dict:
    """What a verified copy must reproduce exactly (RFC §7.3 step 2)."""
    with contextlib.closing(sqlite3.connect(path)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in ("corpus_documents", "corpus_chunks", "corpus_meta")
        }
        rows = conn.execute(
            "SELECT id, doc_key, version, sha256, superseded_at FROM corpus_documents"
        ).fetchall()
        bad_blobs = [
            doc_id
            for doc_id, blob, digest in conn.execute(
                "SELECT id, blob, sha256 FROM corpus_documents WHERE blob IS NOT NULL"
            )
            if hashlib.sha256(blob).hexdigest() != digest
        ]
        meta = conn.execute("SELECT corpus_id FROM corpus_meta").fetchall()
    return {
        "integrity": integrity,
        "foreign_keys": fk,
        "counts": counts,
        "rows": Counter(rows),
        "bad_blobs": bad_blobs,
        "corpus_id": sorted(m[0] for m in meta),
    }


def verify_copy(original: Path, copy: Path) -> None:
    """Raise `MigrationRefused`, naming the failed check, unless `copy` is exact."""
    a, b = _fingerprint(original), _fingerprint(copy)
    if b["integrity"] != "ok":
        raise MigrationRefused(f"integrity_check on the copy returned {b['integrity']!r}")
    if b["foreign_keys"]:
        raise MigrationRefused("foreign_key_check on the copy returned rows")
    if a["counts"] != b["counts"]:
        raise MigrationRefused(f"row counts differ: {a['counts']} != {b['counts']}")
    if a["rows"] != b["rows"]:
        raise MigrationRefused("document ids, versions or hashes differ")
    if a["bad_blobs"] or b["bad_blobs"]:
        raise MigrationRefused("a stored file does not match its recorded sha256")
    if a["corpus_id"] != b["corpus_id"]:
        raise MigrationRefused("corpus_meta.corpus_id differs")


def _document_count(path: Path) -> int:
    with contextlib.closing(sqlite3.connect(path)) as conn:
        try:
            return conn.execute("SELECT COUNT(*) FROM corpus_documents").fetchone()[0]
        except sqlite3.OperationalError:  # no table: a store that never ingested anything
            return 0


async def _meta(db, key: str) -> str | None:
    await db.execute(
        text("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    )
    row = (await db.execute(text("SELECT value FROM app_meta WHERE key = :k"), {"k": key})).first()
    return row[0] if row else None


async def _set_meta(db, key: str, value: str) -> None:
    await db.execute(
        text(
            "INSERT INTO app_meta (key, value) VALUES (:k, :v) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        ),
        {"k": key, "v": value},
    )


async def legacy_project_id(db) -> list[uuid.UUID]:
    """The project the pre-3.1 shared corpus moved into, as the one extra place a historical
    citation may be reopened from (`app/services/cited_documents.py`). Empty when nothing
    was migrated. The route grants nothing else in that project."""
    raw = await _meta(db, MIGRATION_KEY)
    if not raw:
        return []
    try:
        return [uuid.UUID(json.loads(raw)["project_id"])]
    except KeyError, TypeError, ValueError:
        return []


def _remove(path: Path) -> None:
    for suffix in _SQLITE_SIDECARS:
        path.with_name(path.name + suffix).unlink(missing_ok=True)


async def migrate_legacy_corpus(data_dir: str | Path, session_factory, user_id) -> str:
    """Bring this data directory to the per-project layout. Returns the layout in force.

    Every state a crash can leave is handled on the next launch:

    | Found                                        | Action                                     |
    |----------------------------------------------|--------------------------------------------|
    | `shared`, no backup                          | back up, verify, build, commit             |
    | `shared`, a `.tmp` backup only               | discard it and back up again               |
    | `shared`, verified backup, no project store  | build the project store, commit            |
    | `shared`, project store already present      | it is unreachable: rebuild it, commit      |
    | `per_project`, `corpus.sqlite` still present | it is unreachable: delete it               |
    | `per_project`, project store missing/damaged | rebuild from the backup, or refuse to serve|

    A failed check leaves `shared` in force and raises `MigrationRefused`; the caller keeps
    the app running on the shared store with a visible warning.
    """
    from app.models.project import Project

    data = Path(data_dir)
    legacy = data / LEGACY_FILENAME
    backup = data / BACKUP_FILENAME
    lock = data / LOCK_FILENAME

    async with session_factory() as db:
        layout = await _meta(db, LAYOUT_KEY) or SHARED
        recorded = await _meta(db, MIGRATION_KEY)
        await db.commit()

    if layout == PER_PROJECT:
        if legacy.exists():
            _remove(legacy)  # unreachable under this layout; the backup holds its contents
        if recorded:
            info = json.loads(recorded)
            store = data / CORPUS_DIRNAME / f"corpus_{info['project_id']}.sqlite"
            try:
                if not store.exists():
                    raise MigrationRefused("the moved store is missing")
                verify_copy(backup, store)
            except (MigrationRefused, sqlite3.Error) as e:
                logger.error("corpus_legacy_store_damaged", error=str(e))
                if not backup.exists():
                    raise MigrationRefused(f"{e}, and no backup to rebuild from") from e
                _backup(backup, store)
                verify_copy(backup, store)
        lock.unlink(missing_ok=True)
        return PER_PROJECT

    if not legacy.exists() or _document_count(legacy) == 0:
        # Nothing to move. Keep any empty legacy file as the backup rather than delete it.
        if legacy.exists() and not backup.exists():
            _backup(legacy, backup)
        async with session_factory() as db:
            await _meta(db, LAYOUT_KEY)
            await _set_meta(db, LAYOUT_KEY, PER_PROJECT)
            await db.commit()
        if legacy.exists():
            _remove(legacy)
        return PER_PROJECT

    # The project id is fixed before anything is created, and survives a crash in the lock
    # file, so a retry finishes the same move instead of starting a second one.
    if lock.exists():
        project_id = uuid.UUID(json.loads(lock.read_text("utf-8"))["project_id"])
    else:
        project_id = uuid.uuid4()
        lock.write_text(json.dumps({"project_id": str(project_id)}), encoding="utf-8")

    # Step 1-2: a verified backup of the live store. Until the commit the shared store is
    # the authority, so a backup that fails its check was never relied on. It is made again
    # once from the live store, and only a second failure refuses. Reusing it would refuse the
    # move on every launch for ever (AC-37).
    if not backup.exists():
        _backup(legacy, backup)
    try:
        verify_copy(legacy, backup)
    except (MigrationRefused, sqlite3.Error) as e:
        logger.warning("corpus_legacy_backup_remade", error=str(e))
        _remove(backup)
        _backup(legacy, backup)
        verify_copy(legacy, backup)

    # Step 3: the project's store, built from the verified backup, never the live file.
    store = data / CORPUS_DIRNAME / f"corpus_{project_id}.sqlite"
    store.parent.mkdir(parents=True, exist_ok=True)
    _remove(store)  # anything here predates the commit and is unreachable
    _backup(backup, store)
    verify_copy(backup, store)

    # Step 4: the authority point — the project row and the layout in one transaction.
    documents = _document_count(store)
    async with session_factory() as db:
        if await db.get(Project, project_id) is None:
            name = LEGACY_PROJECT_NAME
            taken = set(
                (await db.execute(select(Project.name).where(Project.user_id == user_id)))
                .scalars()
                .all()
            )
            if name in taken:
                name = f"{LEGACY_PROJECT_NAME} ({project_id.hex[:6]})"
            db.add(
                Project(id=project_id, user_id=user_id, name=name, description=LEGACY_PROJECT_NOTE)
            )
        await _meta(db, LAYOUT_KEY)
        await _set_meta(db, LAYOUT_KEY, PER_PROJECT)
        await _set_meta(
            db,
            MIGRATION_KEY,
            json.dumps(
                {
                    "project_id": str(project_id),
                    "documents": documents,
                    "backup_sha256": _file_sha256(backup),
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            ),
        )
        await db.commit()

    # Step 5: retire the shared file. Unreachable from here on; the backup stays forever.
    _remove(legacy)
    lock.unlink(missing_ok=True)
    logger.info("corpus_legacy_migrated", project_id=str(project_id), documents=documents)
    return PER_PROJECT


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
