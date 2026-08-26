# V2 Research Runs: History Page Archive & Delete

## Overview
Adds individual Archive/Restore and permanent Delete capabilities to V2 research runs across both backend hosts (Server API and Desktop Sidecar) and updates the Frontend UI (History Page and `RunCard`) to match the established patterns from V1 legacy sessions.

---

## 1. Backend Changes

### 1.1 `app/api/v1/v2_runs.py`
- **`list_runs` (`GET /v2/runs`)**:
  - Accept query parameter `archived: bool = False`.
  - Filter: `ResearchRun.archived_at.is_not(None)` if `archived` else `ResearchRun.archived_at.is_(None)`.
  - Expose `archived_at` in the returned `runs` summary list.
- **`archive_run` (`POST /v2/runs/{run_id}/archive`)**:
  - Sets `run.archived_at = datetime.now(UTC)` if `run.archived_at is None`.
  - Returns `{"status": "ok", "archived": True, "archived_at": run.archived_at.isoformat()}`.
- **`unarchive_run` (`POST /v2/runs/{run_id}/unarchive`)**:
  - Sets `run.archived_at = None` if `run.archived_at is not None`.
  - Returns `{"status": "ok", "archived": False, "archived_at": None}`.
- **`delete_run` (`DELETE /v2/runs/{run_id}`)**:
  - Refuses if `run.status == "RUNNING"` (409 Conflict: "This run is still running. Wait for it to finish before deleting.").
  - Cleans up restricted foreign keys: deletes associated `Review` records for this run, updates/cleans `ResearchArtifact`, deletes `AgentLog` rows for `session_id == run_id`.
  - Deletes `ResearchRun` (cascading plans, sources, evidence, revisions, claims, links, contradictions).
  - Cleans up LangGraph checkpoints via `checkpoints.delete_thread(str(run_id))`.
  - Returns 204 No Content.

### 1.2 `desktop/sidecar.py`
- Expose matching `GET /v2/runs?archived=...`, `POST /v2/runs/{run_id}/archive`, `POST /v2/runs/{run_id}/unarchive`, and `DELETE /v2/runs/{run_id}` routes.
- Ensure host parity with server router in `tests/test_host_parity.py`.

---

## 2. Frontend Changes

### 2.1 Types (`frontend/lib/types.ts`)
- Add `archived_at?: string | null;` to `V2RunSummary`.

### 2.2 React Query Hooks (`frontend/hooks/v2.ts`)
- Update `v2Keys.runs` to incorporate `showArchived`: `(projectId, archived) => ["v2-runs", projectId ?? null, Boolean(archived)] as const`.
- Update `useV2Runs(projectId?: string | null, archived: boolean = false)`:
  - Query `/v2/runs?${params}` with `archived=${archived}`.
- Add `useArchiveV2Run()`:
  - `POST /v2/runs/{id}/${archived ? "archive" : "unarchive"}`.
  - Invalidates `["v2-runs"]` and `v2Keys.run(id)`.
- Add `useDeleteV2Run()`:
  - `DELETE /v2/runs/{id}`.
  - Removes `v2Keys.run(id)` and invalidates `["v2-runs"]`.

### 2.3 `RunCard` Component (`frontend/components/v2/RunCard.tsx`)
- Add action buttons on hover/focus and touch (matching `SessionCard`):
  - **Archive / Restore Button**: Calls `useArchiveV2Run`, displays success/error toasts.
  - **Delete Button**: Inline two-step confirmation: "Delete permanently? [Yes] [No]". Calls `useDeleteV2Run`, displays toast.
  - `stop(e)` on all action button clicks to prevent navigating into `/research/run?id=...`.

### 2.4 History Page (`frontend/app/(app)/history/page.tsx`)
- Add `showArchived` state (`const [showArchived, setShowArchived] = useState(false)`).
- Pass `showArchived` to `useV2Runs(scope === "project" ? (activeId ?? null) : null, showArchived)`.
- Add toggle button in filter bar: `"Archived"` / `"← Active History"`.
- Adjust header/empty states when `showArchived` is active.

---

## 3. Verification Plan
- **Backend Tests**:
  - Test archive / unarchive / delete behavior on `/v2/runs` in `tests/task/test_v2_api.py`.
  - Verify host parity in `tests/test_host_parity.py`.
  - Run `ruff check` and `pytest`.
- **Frontend Tests**:
  - Run `npm test`, `npm run typecheck`, `npm run lint`.
