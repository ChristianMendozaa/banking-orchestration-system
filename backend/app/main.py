import asyncio
import inspect
import ipaddress
import re
import secrets
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.engine import make_url

from app.api import auth, health, kiosk, knowledge, management, system, tickets
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.metrics import HTTP_DURATION, HTTP_REQUESTS, RATE_LIMITED
from app.core.rate_limit import InMemoryRateLimiter, RateLimitDecision, RedisRateLimiter
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
    if isinstance(_rate_limiter, RedisRateLimiter):
        await _rate_limiter.close()
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


_rate_limiter = (
    RedisRateLimiter(settings.redis_url) if settings.redis_url else InMemoryRateLimiter()
)
# Temporary alias for tests and internal tools that clear global state.
_rate_windows = {} if isinstance(_rate_limiter, RedisRateLimiter) else _rate_limiter.windows


def _client_address(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    try:
        direct_ip = ipaddress.ip_address(direct)
    except ValueError:
        return direct
    trusted = any(
        direct_ip in ipaddress.ip_network(network, strict=False)
        for network in settings.trusted_proxy_cidrs
    )
    if not trusted:
        return direct
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return direct


async def _check_rate_limit(key: str, limit: int) -> RateLimitDecision:
    decision = _rate_limiter.check(key, limit)
    return await decision if inspect.isawaitable(decision) else decision


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
    supplied_trace = request.headers.get("X-Trace-ID")
    try:
        trace_id = str(UUID(supplied_trace)) if supplied_trace else str(uuid4())
    except (ValueError, TypeError, AttributeError):
        trace_id = str(uuid4())
    request.state.trace_id = trace_id
    started = time.monotonic()
    limited = request.method == "POST" and any(
        request.url.path.endswith(suffix)
        for suffix in ("/auth/login", "/kiosk/sessions", "/realtime-token")
    )
    if limited:
        key = f"{_client_address(request)}:{request.url.path}"
        limit = 10 if request.url.path.endswith("/auth/login") else 30
        decision = await _check_rate_limit(key, limit)
        if not decision.allowed:
            RATE_LIMITED.labels(route=_route_path(request)).inc()
            response = JSONResponse(
                status_code=429,
                content={
                    "code": "RATE_LIMITED",
                    "message": "Demasiadas solicitudes; intente nuevamente en un minuto",
                    "details": None,
                    "trace_id": trace_id,
                },
            )
            response.headers["Retry-After"] = str(decision.retry_after)
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    duration = time.monotonic() - started
    route = _route_path(request)
    HTTP_REQUESTS.labels(
        method=request.method,
        route=route,
        status=str(response.status_code),
    ).inc()
    HTTP_DURATION.labels(method=request.method, route=route).observe(duration)
    logger.info(
        "http_request",
        trace_id=trace_id,
        method=request.method,
        path=route,
        status=response.status_code,
        duration_ms=round(duration * 1000, 2),
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


@app.get("/internal/metrics", include_in_schema=False)
async def prometheus_metrics(request: Request) -> Response:
    configured = settings.metrics_token.get_secret_value()
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not configured or not secrets.compare_digest(supplied, configured):
        return Response(status_code=404)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
