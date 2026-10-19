"""What a release of this repository consists of — the facts every check module shares."""

from __future__ import annotations

STAGES = ("ci", "pre-tag", "published", "post-release")
AFTER_TAG = ("published", "post-release")
PASS, FAIL, WARN, SKIP, UNAVAILABLE = "PASS", "FAIL", "WARN", "SKIP", "UNAVAILABLE"

# What desktop.yml publishes, and nothing else: `bundle.targets: "all"` also makes an NSIS
# `.exe` and an `.rpm`, which the release job does not collect. The names are the *served*
# names — GitHub rewrites the bundler's space to a dot, and a SHA256SUMS written with the
# space listed files nobody could download (the v1.0.1 incident).
INSTALLERS = {
    "macOS, Apple Silicon (.dmg)": "Research.Assistant_{v}_aarch64.dmg",
    "Windows, x64 (.msi)": "Research.Assistant_{v}_x64_en-US.msi",
    "Linux, x86-64 (.AppImage)": "Research.Assistant_{v}_amd64.AppImage",
    "Linux, x86-64 (.deb)": "Research.Assistant_{v}_amd64.deb",
}
CHECKSUMS = "SHA256SUMS"
# Floors mirror desktop.yml's: an installer compresses a 140-200 MB engine, and the failure
# being guarded (a shell with no engine in it) is ~5 MB. The AppImage is never smaller than
# the engine it carries uncompressed.
SIZE_FLOOR_MB = {".dmg": 40, ".msi": 40, ".deb": 40, ".AppImage": 60}

IMAGES = ("api", "worker", "frontend")
PLATFORMS = ("linux/amd64", "linux/arm64")

# A10.06: every `actions/setup-python` in `.github/workflows/` runs the backend image's
# Python, except a job named in PYTHON_EXCEPTIONS, which runs exactly the version named
# there. These jobs must keep setting one up, so that dropping the step cannot hide the
# interpreter: the ones that test or stamp the server, desktop.yml's `sidecar`, whose
# interpreter PyInstaller freezes into the desktop engine, and its `shell`, which imports
# the repository's bundle verifier — code the runner's own Python cannot run.
REQUIRED_PYTHON_JOBS = {
    ".github/workflows/ci.yml": ("backend", "golden-e2e"),
    ".github/workflows/release.yml": ("stamp",),
    ".github/workflows/desktop.yml": ("sidecar", "shell"),
}
# Empty: both hosts ship the image's Python, which is what makes the backend suite a test
# of each (AGENTS.md, "What CI actually enforces"). An entry is for a job that cannot follow
# the image yet — the desktop engine, until PyInstaller supports a new Python — and holds it
# at exactly the version named; one that stops describing a job fails as stale.
PYTHON_EXCEPTIONS: dict[tuple[str, str], str] = {}

# A10.06's other half: every stated Python floor — what a contributor, or a third party
# running the bundle verifier, is told to install, and each guard that refuses an older one —
# is the image's Python, the only one CI runs. A lower floor promises an interpreter nothing
# tests; the last one outlived its final CI job by a release. Each pattern captures (major,
# minor) and must match its file. The prose form is compared in every published or top-level
# Markdown file too; the changelog (docs/37) is history and is not.
PROSE_PYTHON_FLOOR = r"\bPython (\d+)\.(\d+)\+"
GUARD_PYTHON_FLOOR = r"\bsys\.version_info < \((\d+), (\d+)\)"
PYTHON_FLOORS: dict[str, tuple[str, ...]] = {
    "backend/pyproject.toml": (r'^target-version = "py(3)(\d+)"',),
    "backend/research_engine/pyproject.toml": (r'^requires-python = ">=(\d+)\.(\d+)"',),
    "Makefile": (r"\bpython(\d+)\.(\d+) -m venv\b",),
    "scripts/release_audit.py": (GUARD_PYTHON_FLOOR, PROSE_PYTHON_FLOOR),
    "CONTRIBUTING.md": (PROSE_PYTHON_FLOOR,),
    "backend/README.md": (PROSE_PYTHON_FLOOR,),
    "docs/getting-started/20-quick-start.md": (PROSE_PYTHON_FLOOR,),
    "docs/developers/32-development.md": (PROSE_PYTHON_FLOOR,),
    "docs/architecture/02-system-architecture.md": (PROSE_PYTHON_FLOOR,),
    "docs/reference/15-bundle-format.md": (PROSE_PYTHON_FLOOR,),
    "backend/research_engine/__init__.py": (GUARD_PYTHON_FLOOR, PROSE_PYTHON_FLOOR),
    "backend/research_engine/verify_bundle.py": (PROSE_PYTHON_FLOOR,),
}

# Required on `main` by ruleset (RG-12). A check dropped from this list is a check a merge
# no longer waits for.
REQUIRED_CHECKS = (
    "backend",
    "frontend",
    "golden-e2e",
    "One version, everywhere",
    "Eval results are write-once",
    "Sidecar (ubuntu-latest)",
    "Sidecar (macos-latest)",
    "Sidecar (windows-latest)",
    "Shell (ubuntu-latest)",
    "Shell (macos-latest)",
    "Shell (windows-latest)",
)

# The one command that opens every macOS build; the download page, both guides and the
# release body must give the *same* one (the 3.0.1 incident was four surfaces sending users
# to an Open Anyway button the damaged builds never offered).
MACOS_UNQUARANTINE = 'xattr -dr com.apple.quarantine "/Applications/Research Assistant.app"'

# Paths whose change alters what a run *produces*, so a release carrying one needs a new
# committed evaluation or a recorded waiver (docs/08 "Quality gates": prompt or model changes
# carry an evaluation run).
QUALITY_PATHS = (
    "backend/research_engine/prompts.py",
    "backend/research_engine/prompt_composition.py",
    "backend/research_engine/graph.py",
    "backend/research_engine/routing_rules.py",
    "backend/research_engine/retrievers.py",
    "backend/research_engine/tools.py",
    "backend/research_engine/claims.py",
    "backend/research_engine/citation_rate.py",
    "backend/research_engine/catalog.py",
    "backend/app/services/model_routing.py",
)
BUNDLE_FORMAT_PATHS = (
    "backend/research_engine/bundle.py",
    "backend/research_engine/verify_bundle.py",
    "backend/app/run_bundle.py",
)

# The public pages RG-11 checks after every deploy, plus the two static ones.
SITE_PAGES = ("/", "/why/", "/docs/", "/download/", "/releases/")
SITE_ROUTES = ("/", "/why", "/docs", "/download", "/releases", "/license", "/source")
