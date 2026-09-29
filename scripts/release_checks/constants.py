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
