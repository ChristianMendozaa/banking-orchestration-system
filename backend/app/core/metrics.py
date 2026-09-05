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

# Per-stage latency inside the turn a customer is standing there waiting through. The
# acknowledgement the persona used to be ordered to say ("déjame revisar eso") was covering
# for a number nobody had measured: a general question is a classification call, an
# embedding batch, retrieval and a grounding call, all serial, all inside one HTTP request
# and one Postgres row lock. Removing the filler only helps if the wait behind it is known,
# so it is measured per stage rather than as one opaque total.
#
# Labels stay low-cardinality on purpose: a session id here would create a new time series
# per customer.
STAGE_DURATION = Histogram(
    "orchestration_stage_duration_seconds",
    "Duracion de cada etapa del turno del kiosco",
    ("stage",),
)
