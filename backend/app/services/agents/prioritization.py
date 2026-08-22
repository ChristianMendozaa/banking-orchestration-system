"""The priority engine.

Deterministic and synchronous -- no model call, no weights, no tuning surface. Category
picks a base priority; `distress_detected` and `preferential_attention` each bump it at
most one step, in that order.

`turn_nodes.persist_requirement` calls this directly rather than through a graph node:
it is a pure scoring function with no branching worth making declarative.
"""

from app.domain.enums import Category, Priority


class PrioritizationAgent:
    _order = [Priority.BAJO, Priority.MEDIO, Priority.ALTO, Priority.CRITICO]

    def run(
        self,
        category: Category,
        summary: str,
        preferential: bool,
        urgency_detected: bool = False,
        security_incident: bool = False,
        distress_detected: bool = False,
    ) -> Priority:
        lowered = summary.lower()
        if category == Category.REPORTE_FRAUDE or "movimiento no reconocido" in lowered:
            priority = Priority.CRITICO
        elif category == Category.BLOQUEO_TARJETA or (security_incident and urgency_detected):
            priority = Priority.ALTO
        elif category in {Category.SOLICITUD_CREDITO, Category.BANCA_DIGITAL} or urgency_detected:
            priority = Priority.MEDIO
        else:
            priority = Priority.BAJO
        if distress_detected and priority in {Priority.BAJO, Priority.MEDIO}:
            priority = self._order[self._order.index(priority) + 1]
        if preferential and priority not in {Priority.ALTO, Priority.CRITICO}:
            priority = self._order[self._order.index(priority) + 1]
        return priority
