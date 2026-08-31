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
download header policy), the run route module (for its request models), and
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
        "app.schemas.runs",
        "app.services.local_llm",
        "app.services.sse",
        # In the lifecycle's import tree since run deletion had to clear project memory.
        # It reads `settings.corpus_path`, and doing so at module scope pulled `app.config`
        # — and its two required environment variables — into every sidecar startup.
        "app.services.memory",
        "app.run_lifecycle",
        # Relocated so the desktop could declare the same `response_model` the server does
        # on the twelve shared operations that had none. They sat in `app/api/v1/models.py`
        # and `app/api/v1/corpus.py`, which reach `app.config`.
        "app.schemas.models",
        "app.schemas.corpus",
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


def test_run_request_models_have_exactly_one_home():
    """Same rule for the run request bodies: both hosts must accept the same contract."""
    from app.api.v1 import runs as runs_api
    from app.schemas import runs as run_schemas

    assert runs_api.CreateRunRequest is run_schemas.CreateRunRequest
    assert runs_api.PlanReviewRequest is run_schemas.PlanReviewRequest
    assert runs_api.ReportReviewRequest is run_schemas.ReportReviewRequest


def test_model_and_corpus_response_shapes_have_exactly_one_home():
    """The twelve operations that used to escape the parity shape check.

    The desktop declared no `response_model` on any of them, so its hand-built dicts were
    never compared to the server's declared shape — `GET /auth/me` omitted `is_active`,
    every `api_key_*` field and the whole `preferences` object, and nothing objected. The
    shapes could not be declared where they were, because both route modules reach
    `app.config` and an installed app has none of it (#50).

    Identity, not equality: two classes with the same fields are two homes, and the second
    is the one that gets forgotten.
    """
    from app.api.v1 import corpus as corpus_api
    from app.api.v1 import models as models_api
    from app.schemas import corpus as corpus_schemas
    from app.schemas import models as model_schemas

    assert corpus_api.DocumentResponse is corpus_schemas.DocumentResponse
    assert corpus_api.CorpusStatusResponse is corpus_schemas.CorpusStatusResponse
    assert models_api.CatalogResponse is model_schemas.CatalogResponse
    assert models_api.RoutingResponse is model_schemas.RoutingResponse
    assert models_api.LocalLLMStatusResponse is model_schemas.LocalLLMStatusResponse
    assert models_api.CustomEndpointStatusResponse is model_schemas.CustomEndpointStatusResponse


def test_the_desktop_declares_the_same_response_shapes_it_now_imports():
    """The relocation is only worth anything if the desktop actually uses it.

    Asserted on the module the sidecar imports rather than on its routes, so this fails at
    the import boundary — the place the fix has to hold — rather than after an app is built.
    """
    from app.schemas.auth import UserResponse
    from app.schemas.corpus import CorpusStatusResponse, DocumentResponse
    from app.schemas.models import CatalogResponse, RoutingResponse
    from desktop import sidecar

    assert sidecar.UserResponse is UserResponse
    assert sidecar.DocumentResponse is DocumentResponse
    assert sidecar.CorpusStatusResponse is CorpusStatusResponse
    assert sidecar.CatalogResponse is CatalogResponse
    assert sidecar.RoutingResponse is RoutingResponse


#: Imported by the sidecar's run routes at *request* time rather than at startup, which is
#: why the startup assertions above never saw them. `create_sidecar_app` imports each
#: handler inside the route body so the module stays out of the launch path.
#: Modules the sidecar imports when a request arrives rather than at startup, so the
#: guard below can walk them. `app.run_execution` joined the list when the desktop gained an
#: in-process run driver: `_drive_run` imports it per run for `persist_outcome` and
#: `lifecycle_event`, and it reaches `app.runtime` → `app.config` → `app.db.base`, which is
#: precisely the chain that decides whether a server-only driver gets pulled in.
LAZY_REQUEST_IMPORTS = (
    "app.api.v1.runs",
    "app.run_execution",
    "app.run_dispatch",
    # The server's Celery adapter, which `app.api.v1.runs` imports at module scope so the
    # server can bind `Depends(get_run_dispatcher)`. The desktop never calls it — it passes
    # its own dispatcher — but it does import it, so it has to stay free of `celery` at
    # module scope exactly as it was when it lived in `app.run_dispatch`.
    "app.workers.dispatch",
    # Phase 7: the desktop delegates its session routes the way it delegates `/runs`.
    "app.api.v1.research",
    # Phase 8: the desktop delegates its project routes the same way. Reaches
    # `app.dependencies` -> `app.config` and `app.db.redis` exactly as `app.api.v1.runs`
    # already does above — the `os.environ.setdefault` calls in `create_sidecar_app`
    # exist for this: `Settings()` builds on the synthetic values instead of raising, and
    # `redis` itself stays out of `sys.modules` because `app.db.redis` defers its own
    # `import redis.asyncio` to inside its functions. Named here so this delegation is
    # actually walked rather than merely assumed to be as safe as the run routes.
    "app.api.v1.projects",
    # Same phase, same reasoning: the per-project corpus routes delegate too.
    "app.api.v1.corpus",
)


def _spec_excludes() -> list[str]:
    """The exclude list, read from `research-sidecar.spec` rather than copied.

    A second copy of this list is a second thing to forget: the spec is what PyInstaller
    obeys, so the spec is what the test has to read. Parsed rather than imported because
    the spec is only valid under PyInstaller (it references injected globals like
    SPECPATH).
    """
    import ast
    from pathlib import Path

    spec = Path(__file__).resolve().parents[2] / "desktop" / "research-sidecar.spec"
    tree = ast.parse(spec.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "excludes" for t in node.targets
        ):
            return [ast.literal_eval(e) for e in node.value.elts]
    raise AssertionError("no `excludes` assignment found in research-sidecar.spec")


def test_lazy_v2_imports_pull_in_no_excluded_package():
    """What the desktop imports *per request* must also fit in the bundle.

    `test_sidecar_import_tree_excludes_weasyprint` walks the startup tree only, so it is
    blind by construction to the run handlers — they are imported when the first run request
    arrives. That blind spot shipped: the spec excludes `redis` because the desktop speaks
    SQLite only, `app.api.v1.runs` imported it at module scope for the server stream's
    `Depends(get_redis)`, and every run route on the packaged app answered 500 with
    `ModuleNotFoundError: No module named 'redis'`. From a source checkout the package is
    installed, so nothing anywhere was red.

    Asserting on `sys.modules` rather than on the built bundle keeps this a fast unit test
    that still measures the real thing: a package the sidecar imports is a package
    PyInstaller must ship, and every name below is one the spec refuses to.
    """
    excluded = _spec_excludes()
    imports = "; ".join(f"import {m}" for m in LAZY_REQUEST_IMPORTS)
    # The app is *built* first, with the server environment stripped, because the host's
    # own configuration decides which drivers the shared modules then load. Asserting on a
    # bare import instead would measure the suite's environment: `conftest` exports a
    # Postgres DSN, so `app.db.base` would pull in `asyncpg` — excluded, but excluded for a
    # host that never sees that DSN. Building the app the way the launcher does is what
    # makes this a statement about the shipped artifact.
    result = _run(
        "import sys, json, tempfile; import desktop.sidecar;"
        "desktop.sidecar.create_sidecar_app("
        "data_dir=tempfile.mkdtemp(), token='guard', fake=True);"
        f"{imports};"
        f"print(json.dumps([n for n in {excluded!r} if n in sys.modules]))",
        strip_server_env=True,
    )
    assert result.returncode == 0, result.stderr
    found = result.stdout.strip().splitlines()[-1]
    assert found == "[]", (
        f"the sidecar's request-time import tree pulls in {found}, which "
        f"research-sidecar.spec excludes — these 500 in the packaged app only"
    )
