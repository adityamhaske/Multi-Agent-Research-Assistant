# research-sidecar.spec — PyInstaller one-dir build of the desktop sidecar
# (docs/12 M9, docs/13 §7).
#
#   cd backend && pyinstaller desktop/research-sidecar.spec
#
# Output: dist/research-sidecar/research-sidecar (+ collected libs). The Tauri
# bundler drops that directory next to the shell executable; the shell resolves
# `research-sidecar` beside its own binary (desktop/src/lib.rs).
#
# Bundle rules:
#  * WeasyPrint is EXCLUDED by design — desktop PDF is WebView print-to-PDF
#    (docs/13 §7); its GTK chain is a Windows packaging tar pit. A backend test
#    (test_sidecar_import_tree_excludes_weasyprint) proves the import tree never
#    touches it, so the exclude can never silently break the sidecar.
#  * Server-only transports (asyncpg/psycopg/redis/celery/alembic) are excluded
#    the same way: the sidecar speaks SQLite only.
#  * Providers and keyring backends are imported lazily, so they must be listed
#    explicitly — that is what hiddenimports below is for.

import os

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH is injected by PyInstaller: this file's directory (backend/desktop/).
_BACKEND_ROOT = os.path.dirname(SPECPATH)

hiddenimports = [
    # SQLite async driver for SQLAlchemy (create_async_engine sqlite+aiosqlite).
    "aiosqlite",
    # LangGraph SQLite checkpointing.
    "langgraph.checkpoint.sqlite.aio",
    # uvicorn pieces that are resolved from strings at runtime.
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # LLM providers — llm_factory imports them lazily per route.
    "langchain_google_genai",
    "langchain_anthropic",
    "langchain_openai",
    # pydantic[email] used by app.schemas.
    "email_validator",
]

# OS keychain backends are chosen at runtime by keyring; ship them all and let
# keyring pick the platform one (macOS Keychain / Windows Credential Locker /
# SecretService).
hiddenimports += collect_submodules("keyring.backends")

excludes = [
    "weasyprint",
    "celery",
    "redis",
    "asyncpg",
    "psycopg",
    "alembic",
    "pytest",
    "tkinter",
]

a = Analysis(
    [os.path.join(SPECPATH, "sidecar.py")],
    pathex=[_BACKEND_ROOT],
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="research-sidecar",
    debug=False,
    strip=False,
    # The shell reads the handshake from stdout; a console keeps stderr visible
    # when the sidecar is run standalone for debugging.
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    name="research-sidecar",
)
