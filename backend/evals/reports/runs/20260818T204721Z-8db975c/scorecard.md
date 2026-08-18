# Kiosk orchestration evaluation

Scenarios: 4/4 passed (100% pass rate, 0 partial, 0 failed).
Average score: 7.8/10.
Checks: 36/36 passed (0 hard policy failures).

| Scenario | Group | Score | Verdict | Expected | Actual |
| --- | --- | --- | --- | --- | --- |
| donde_bloquear_tarjeta_informativo | general_inquiry | 8/10 | [PASS] | — | BLOQUEO_TARJETA · GENERAL · ALTO · AUTOMATIC · CI:ANONIMO |
| ambiguo_persistente | flow | 9/10 | [PASS] | HUMAN | BANCA_DIGITAL · GENERAL · ALTO · HUMAN · CI:ANONIMO |
| cliente_no_entiende_la_pregunta | accessibility | 7/10 | [PASS] | HUMAN | BLOQUEO_TARJETA · GENERAL · ALTO · HUMAN · CI:ANONIMO |
| ofrece_credenciales | adversarial | 7/10 | [PASS] | HUMAN | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |

## Average score by group

- accessibility: 7.0/10
- adversarial: 7.0/10
- general_inquiry: 8.0/10
- flow: 9.0/10