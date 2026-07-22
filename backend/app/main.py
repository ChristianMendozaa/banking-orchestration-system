import asyncio
import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import make_url

from app.api import auth, health, kiosk, knowledge, management, system, tickets
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.rate_limit import InMemoryRateLimiter
from app.services.retention import conversation_retention_loop

settings = get_settings()
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("application_started", environment=settings.app_env)
    database_host = make_url(settings.database_url).host
    if settings.supabase_url and database_host in {"localhost", "127.0.0.1"}:
        logger.warning(
            "supabase_not_connected",
            detail="SUPABASE_URL existe, pero DATABASE_URL continua apuntando a la base local",
        )
    retention_stop = asyncio.Event()
    retention_task = asyncio.create_task(conversation_retention_loop(settings, retention_stop))
    yield
    retention_stop.set()
    await retention_task
    logger.info("application_stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API del sistema de orquestacion de atencion bancaria",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_rate_limiter = InMemoryRateLimiter()
# Alias temporal para las pruebas y herramientas internas que limpian el estado global.
_rate_windows = _rate_limiter.windows


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str):
        return route_path
    return re.sub(
        r"/[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}(?=/|$)",
        "/{id}",
        request.url.path,
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID") or str(uuid4())
    request.state.trace_id = trace_id
    started = time.monotonic()
    limited = request.method == "POST" and any(
        request.url.path.endswith(suffix)
        for suffix in ("/auth/login", "/kiosk/sessions", "/realtime-token")
    )
    if limited:
        key = f"{request.client.host if request.client else 'unknown'}:{request.url.path}"
        limit = 10 if request.url.path.endswith("/auth/login") else 30
        if not _rate_limiter.allow(key, limit):
            response = JSONResponse(
                status_code=429,
                content={
                    "code": "RATE_LIMITED",
                    "message": "Demasiadas solicitudes; intente nuevamente en un minuto",
                    "details": None,
                    "trace_id": trace_id,
                },
            )
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    logger.info(
        "http_request",
        trace_id=trace_id,
        method=request.method,
        path=_route_path(request),
        status=response.status_code,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return response


install_error_handlers(app)
for api_router in (
    health.router,
    system.router,
    auth.router,
    kiosk.router,
    tickets.router,
    management.router,
    knowledge.router,
):
    app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs"}
