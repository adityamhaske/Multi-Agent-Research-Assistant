"""
The release audit's checks, one module per area. RELEASE.md is the process; `release_audit.py`
runs these concurrently and reports.

| Module | Phases | Needs |
|---|---|---|
| `repository` | 0-2 | the checkout |
| `workflows` | 3, 6 | the checkout; GitHub Actions for run evidence |
| `images` | 10 | the container registry (anonymous) |
| `github_release` | 11 | the GitHub Release and its assets |
| `site` | 12-17 | the checkout; the live site |
| `security` | 18 | the checkout; code-scanning and Dependabot |
| `upgrade` | 19, 21, 22 | the checkout; the release record |

Pure judgements live in `evaluate` so the tests can plant each historical failure without a
release existing; importing this package registers every check.
"""

from . import github_release, images, repository, security, site, upgrade, workflows  # noqa: F401
from .core import REGISTRY

GROUPS = ("repository", "workflows", "images", "github_release", "site", "security", "upgrade")

__all__ = ["GROUPS", "REGISTRY"]
