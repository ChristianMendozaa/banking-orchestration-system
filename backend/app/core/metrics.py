from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "orchestration_http_requests_total",
    "Solicitudes HTTP procesadas",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "orchestration_http_request_duration_seconds",
    "Duracion de solicitudes HTTP",
    ("method", "route"),
)
RATE_LIMITED = Counter(
    "orchestration_rate_limited_total",
    "Solicitudes rechazadas por limite",
    ("route",),
)
