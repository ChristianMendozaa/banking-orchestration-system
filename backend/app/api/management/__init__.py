"""Manager-facing endpoints, one module per concern.

| Module | Endpoint |
| --- | --- |
| `metrics` | `GET /management/metrics` |
| `cases` | `GET /management/cases` |
| `mutations` | the three supervised-override `PATCH`es |

`filters` and `audit` hold what those share. The sub-routers are declared bare; the
prefix and the tag are supplied here, once, so paths and OpenAPI operation ids are
exactly what they were when this was a single module.
"""

from fastapi import APIRouter

from app.api.management import cases, metrics, mutations

router = APIRouter(prefix="/management", tags=["Gestion gerencial"])
router.include_router(metrics.router)
router.include_router(cases.router)
router.include_router(mutations.router)

__all__ = ["router"]
