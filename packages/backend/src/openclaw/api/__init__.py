"""API route aggregation.

All routers registered here get mounted in main.py.

Learn: Auth is applied at the include_router level using FastAPI's
dependencies parameter. This protects all routes in each router
without modifying individual handlers. Health and auth routers are
open (no auth required).
"""

from fastapi import APIRouter, Depends

from openclaw.api.agent_runs import router as agent_runs_router
from openclaw.api.alerts import router as alerts_router
from openclaw.api.auth import router as auth_router
from openclaw.api.dispatch import router as dispatch_router
from openclaw.api.git import router as git_router
from openclaw.api.health import router as health_router
from openclaw.api.human_requests import router as human_requests_router
from openclaw.api.reviews import router as reviews_router
from openclaw.api.sessions import router as sessions_router
from openclaw.api.settings import router as settings_router
from openclaw.api.tasks import router as tasks_router
from openclaw.api.teams import router as teams_router
from openclaw.api.analytics import router as analytics_router
from openclaw.api.pipelines import router as pipelines_router
from openclaw.api.sandbox import router as sandbox_router
from openclaw.api.security import router as security_router
from openclaw.api.webhooks import router as webhooks_router
from openclaw.auth.dependencies import get_current_user

# All protected routers require authentication
_auth = [Depends(get_current_user)]

api_router = APIRouter(prefix="/api/v1")

# Open routes — no auth required
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, tags=["auth"])

# Protected routes — require valid JWT or API key
api_router.include_router(teams_router, tags=["teams", "agents", "repos"], dependencies=_auth)
api_router.include_router(tasks_router, tags=["tasks", "messages"], dependencies=_auth)
api_router.include_router(git_router, tags=["git"], dependencies=_auth)
api_router.include_router(sessions_router, tags=["sessions", "costs"], dependencies=_auth)
api_router.include_router(human_requests_router, tags=["human-requests"], dependencies=_auth)
api_router.include_router(reviews_router, tags=["reviews", "merge"], dependencies=_auth)
api_router.include_router(dispatch_router, tags=["dispatch"], dependencies=_auth)
api_router.include_router(agent_runs_router, tags=["agent-runs"], dependencies=_auth)
api_router.include_router(webhooks_router, tags=["webhooks"], dependencies=_auth)
api_router.include_router(pipelines_router, tags=["pipelines"], dependencies=_auth)
api_router.include_router(sandbox_router, tags=["sandbox"], dependencies=_auth)
api_router.include_router(analytics_router, tags=["analytics"], dependencies=_auth)
api_router.include_router(alerts_router, tags=["alerts"], dependencies=_auth)
api_router.include_router(settings_router, tags=["settings"], dependencies=_auth)
api_router.include_router(security_router, tags=["security"], dependencies=_auth)
