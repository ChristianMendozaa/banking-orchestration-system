"""Category keyword rules.

Shared by `ClassificationAgent._fallback` (which needs them to classify at all when the
provider is down) and by `sensitivity_floor` (which needs them to second-guess a
provider that answered). Keeping one copy is the point: a floor that drifts from the
fallback is a floor nobody can reason about.

Leaf module: imports nothing from the application except enums.
"""

from app.domain.enums import Category

_CATEGORY_RULES: tuple[tuple[Category, tuple[str, ...]], ...] = (
    (
        Category.REPORTE_FRAUDE,
        (
            "fraude",
            "movimiento no reconocido",
            "compra no reconocida",
            "no reconozco",
            "estafa",
        ),
    ),
    (
        Category.BLOQUEO_TARJETA,
        ("bloquear", "bloqueo", "tarjeta perdida", "tarjeta robada", "extrav"),
    ),
    (
        Category.BANCA_DIGITAL,
        ("banca digital", "banca en linea", "aplicacion", "contraseña", "acceso"),
    ),
    (
        Category.SOLICITUD_CREDITO,
        ("credito", "crédito", "prestamo", "préstamo", "hipotecario"),
    ),
    (
        Category.CONSULTA_GENERAL,
        ("horario", "requisito", "abrir una cuenta", "sucursal", "producto"),
    ),
)


def category_from_keywords(text: str) -> Category | None:
    """First matching rule wins, matching `_fallback`'s original `next(...)` order."""
    lowered = text.lower()
    return next(
        (
            candidate
            for candidate, keywords in _CATEGORY_RULES
            if any(keyword in lowered for keyword in keywords)
        ),
        None,
    )
