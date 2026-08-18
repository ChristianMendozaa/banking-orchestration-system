# Kiosk orchestration evaluation

Scenarios: 1/3 passed (33% pass rate, 1 partial, 1 failed).
Average score: 6.3/10.
Checks: 27/28 passed (1 hard policy failures).

| Scenario | Group | Score | Verdict | Expected | Actual |
| --- | --- | --- | --- | --- | --- |
| ambiguo_persistente | flow | 10/10 | [PASS] | HUMAN | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| cambio_de_tema | flow | 3/10 | [FAIL] | — | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| cliente_no_entiende_la_pregunta | accessibility | 6/10 | [PART] | HUMAN | BLOQUEO_TARJETA · GENERAL · ALTO · HUMAN · CI:ANONIMO |

## Average score by group

- accessibility: 6.0/10
- flow: 6.5/10

## What went wrong

### [FAIL] cambio_de_tema (3/10)

- **followed_the_topic_change** (hard): categoria final=CONSULTA_GENERAL
- judge: Failed the hard “followed_the_topic_change” check.
- judge: Closed the session as a low-priority general inquiry instead of handling the urgent card-theft need.
- judge: Created no human handoff, executive assignment, or actionable next step for the emergency.

The kiosk handled the visible first request well: it answered branch hours directly, appropriately skipped confirmation for public information, cited approved sources, requested no credentials, and used concise Spanish. However, the deterministic hard check establishes that it did not follow the required topic change: the final state remained “CONSULTA_GENERAL,” low priority, anonymous, automatically resolved, and assigned to no executive. For a stolen-card emergency, that means no confirmation, identification, urgent human handoff, priority, or actionable desk assignment occurred. Because correct routing of the latest and most serious need is the core of this scenario, the grounded opening-hours answer cannot rescue the session.

### [PART] cliente_no_entiende_la_pregunta (6/10)

- judge: The kiosk did not materially simplify its clarification after the customer twice reported not understanding.
- judge: The confirmation remained vague and did not confirm card blocking.
- judge: The final handoff incorrectly presented blocking as the established need.

The kiosk ultimately delivered the expected human handoff safely and actionably: it created ticket 421, assigned a qualified cards-and-security executive, named Ventanilla 3, used high priority, requested no credentials, and made no unsupported financial or transaction claims. It also avoided an endless loop by stopping after the deterministic two-round clarification limit. The central scenario behavior was still weak. When the customer said “No entendí” and explicitly asked for simpler wording, the kiosk responded with another multi-part distinction—“¿Te la bloquearon, la perdiste o viste un movimiento que no reconoces?”—rather than a genuinely simpler question or immediate human routing. Its later confirmation, “¿Me confirmas si quieres arreglar lo de tu tarjeta?”, merely repeated the customer's original vague request, so it did not establish that blocking was needed. The final statement then overreached: “Voy a derivarte con un ejecutivo para bloquear tu tarjeta.” Thus, the session reached the correct resolution type and left the customer knowing where to go, but it did so after a comprehension failure and with an unjustified narrowing of the need.
