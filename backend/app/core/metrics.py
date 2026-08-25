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
GROUNDING_ATTEMPTS = Counter(
    "orchestration_grounding_attempts_total",
    "Intentos de fundamentacion por resultado interno",
    ("outcome",),
)
CLARIFICATION_OUTCOMES = Counter(
    "orchestration_clarification_outcomes_total",
    "Resultados estructurados de respuestas de aclaracion",
    ("outcome",),
)
UNRESOLVED_HANDOFFS = Counter(
    "orchestration_unresolved_handoffs_total",
    "Derivaciones donde la accion bancaria quedo sin precisar",
)
