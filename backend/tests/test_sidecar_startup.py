"""
The packaged desktop sidecar must start without server configuration (#50).

**The failure this file exists to prevent.** The PyInstaller-packaged sidecar died on
launch, on all three platforms, with:

    File "app/config.py", line 200, in get_settings
        return Settings()
    pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings
    database_url
      Field required
    jwt_secret_key
      Field required

The desktop host has neither: it uses SQLite and the OS keychain by design. Three
different startup imports reached `app.config` transitively — the corpus route (for the
download header policy), the V2 route module (for its request models), and
`app.services.local_llm`. The `Sidecar` CI job failed, the Tauri `Shell` job was skipped
because it `needs: sidecar`, and **no installer was produced at all**.

**Why the existing coverage missed it.** `test_sidecar_import_tree_excludes_weasyprint`
imports the sidecar in a subprocess that inherits the test environment, and CI's backend
job sets `DATABASE_URL` and `JWT_SECRET_KEY`. `Settings()` therefore built fine there and
the import succeeded — the test was green while the shipped artifact was broken.

**So the load-bearing assertion here is `app.config` never entering `sys.modules`**, not
"the import happened to work". That holds on a fully configured developer machine, and it
survives `Settings`' `env_file="../.env"`, which would otherwise let a repo-root `.env`
mask the defect exactly the way CI's environment did.
"""

from __future__ import annotations

import os
import subprocess
import sys

#: Reaching any of these from sidecar import means the desktop host has taken on a
#: server-only dependency: `app.config` builds `Settings`, and `app.db` opens the
#: server's engine. Both are Postgres/JWT-shaped and neither exists on the desktop.
FORBIDDEN_AT_STARTUP = ("app.config", "app.db.base", "app.dependencies", "app.adapters")


def _run(code: str, *, strip_server_env: bool) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if strip_server_env:
        for key in ("DATABASE_URL", "JWT_SECRET_KEY", "ENCRYPTION_KEY", "REDIS_URL"):
            env.pop(key, None)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_sidecar_startup_never_imports_server_configuration():
    """The contract, stated as an import boundary.

    Independent of whether `Settings` *could* be built in this environment, so it fails on
    a configured machine too rather than only where the packaged build runs.
    """
    forbidden = ", ".join(repr(m) for m in FORBIDDEN_AT_STARTUP)
    result = _run(
        "import sys, desktop.sidecar\n"
        f"leaked = [m for m in ({forbidden},) if m in sys.modules]\n"
        "assert not leaked, 'sidecar startup imported server-only modules: %r' % leaked\n",
        strip_server_env=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_sidecar_imports_without_database_url_or_jwt_secret():
    """The packaged failure, reproduced directly.

    This is what the frozen binary does on a user's machine: no server environment at all.
    """
    result = _run("import desktop.sidecar\n", strip_server_env=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ValidationError" not in result.stderr


def test_shared_modules_the_sidecar_imports_are_configuration_free():
    """The relocated utilities, guarded individually.

    Named one by one so a regression points at the module that regressed rather than at
    the sidecar as a whole.
    """
    for module in (
        "app.services.document_headers",
        "app.schemas.v2",
        "app.services.local_llm",
        "app.services.sse",
    ):
        result = _run(f"import {module}\n", strip_server_env=True)
        assert result.returncode == 0, f"{module} needs server configuration:\n{result.stderr}"


def test_download_header_policy_has_exactly_one_home():
    """`app.api.v1.corpus` re-exports rather than restating it.

    The server route is where callers and tests have always found `download_headers`; the
    policy itself moved so the desktop could import it without the route's config chain.
    A second *copy* would be the duplication the relocation exists to avoid, so assert
    both names resolve to the same object.
    """
    from app.api.v1 import corpus
    from app.services import document_headers

    assert corpus.download_headers is document_headers.download_headers
    assert corpus.media_type_for is document_headers.media_type_for


def test_v2_request_models_have_exactly_one_home():
    """Same rule for the V2 request bodies: both hosts must accept the same contract."""
    from app.api.v1 import v2_runs
    from app.schemas import v2

    assert v2_runs.CreateRunRequest is v2.CreateRunRequest
    assert v2_runs.PlanReviewRequest is v2.PlanReviewRequest
    assert v2_runs.ReportReviewRequest is v2.ReportReviewRequest
