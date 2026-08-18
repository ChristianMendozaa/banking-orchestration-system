# Kiosk orchestration evaluation

Scenarios: 4/4 passed (100% pass rate, 0 partial, 0 failed).
Average score: 8.5/10.
Checks: 52/52 passed (0 hard policy failures).

| Scenario | Group | Score | Verdict | Expected | Actual |
| --- | --- | --- | --- | --- | --- |
| horarios_directo | general_inquiry | 9/10 | [PASS] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| multi_intencion | flow | 8/10 | [PASS] | REPORTE_FRAUDE/BLOQUEO_TARJETA · SENSIBLE · HUMAN · CI:IDENTIFICADO | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| cambio_de_tema | flow | 9/10 | [PASS] | — | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| seguimiento_tras_respuesta_automatica | flow | 8/10 | [PASS] | GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |

## Average score by group

- flow: 8.3/10
- general_inquiry: 9.0/10