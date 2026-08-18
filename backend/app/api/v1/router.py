from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.corpus import router as corpus_router
from app.api.v1.models import router as models_router
from app.api.v1.projects import router as projects_router
from app.api.v1.research import router as research_router
from app.api.v1.threads import router as threads_router
from app.api.v1.v2_runs import router as v2_runs_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(research_router)
api_router.include_router(corpus_router)
api_router.include_router(chat_router)
api_router.include_router(threads_router)
api_router.include_router(models_router)
api_router.include_router(v2_runs_router)
