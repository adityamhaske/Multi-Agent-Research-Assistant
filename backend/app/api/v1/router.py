"""The v1 surface, assembled.

`/version` is declared here rather than in a feature router because it belongs to no
feature: it says which build is answering. It sits under `/api/v1` rather than beside
`/health` so that **both hosts serve it at the same path** — the desktop has no top-level
routes at all (everything is behind the per-launch token), and a client that had to know
which host it was talking to in order to ask "what are you?" would be exactly the
`isDesktop` branch this work exists to remove.
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.corpus import router as corpus_router
from app.api.v1.models import router as models_router
from app.api.v1.projects import router as projects_router
from app.api.v1.research import router as research_router
from app.api.v1.runs import router as runs_router
from app.api.v1.threads import router as threads_router
from app.schemas.capabilities import SERVER, Capabilities
from research_engine.build_info import build_info

api_router = APIRouter()


@api_router.get("/capabilities", response_model=Capabilities, tags=["Health"])
async def capabilities() -> Capabilities:
    """What this host can do, so the client stops inferring it from the build flag."""
    return SERVER


@api_router.get("/version", tags=["Health"])
async def version():
    """Which build this is, and which commit produced it.

    Unauthenticated on the server: it discloses nothing a client cannot infer from the
    OpenAPI document, and the point is that a maintainer reading a bug report can ask a
    running deployment what it is. The desktop serves the same payload behind its
    per-launch token, because that host's boundary is "one token, no exceptions".

    `unknown` where a build was never stamped — `research_engine/build_info.py` explains
    why that is not filled in from the working tree.
    """
    return build_info().as_dict()


api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(research_router)
api_router.include_router(corpus_router)
api_router.include_router(chat_router)
api_router.include_router(threads_router)
api_router.include_router(models_router)
api_router.include_router(runs_router)
