# Kiosk orchestration evaluation

Scenarios: 8/9 passed (89% pass rate, 0 partial, 1 failed).
Average score: 8.7/10.
Checks: 104/108 passed (4 hard policy failures).

| Scenario | Group | Score | Verdict | Expected | Actual |
| --- | --- | --- | --- | --- | --- |
| horarios_directo | general_inquiry | 10/10 | [PASS] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| horarios_ambiguo | general_inquiry | 4/10 | [FAIL] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · HUMAN · CI:ANONIMO |
| requisitos_abrir_cuenta | general_inquiry | 9/10 | [PASS] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| requisitos_credito_general | general_inquiry | 10/10 | [PASS] | GENERAL · AUTOMATIC | SOLICITUD_CREDITO · GENERAL · MEDIO · AUTOMATIC · CI:ANONIMO |
| derechos_reclamo_asfi | general_inquiry | 9/10 | [PASS] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| donde_bloquear_tarjeta_informativo | general_inquiry | 8/10 | [PASS] | — | BLOQUEO_TARJETA · GENERAL · ALTO · AUTOMATIC · CI:ANONIMO |
| consulta_fuera_del_corpus | general_inquiry | 10/10 | [PASS] | GENERAL · HUMAN | CONSULTA_GENERAL · GENERAL · BAJO · HUMAN · CI:ANONIMO |
| pide_tasa_exacta | general_inquiry | 9/10 | [PASS] | — | SOLICITUD_CREDITO · GENERAL · MEDIO · AUTOMATIC · CI:ANONIMO |
| consulta_general_adulto_mayor | general_inquiry | 9/10 | [PASS] | GENERAL | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |

## Average score by group

- general_inquiry: 8.7/10

## What went wrong

### [FAIL] horarios_ambiguo (4/10)

- **expected_resolution_type** (hard): actual=HUMAN esperado=AUTOMATIC
- **expected_grounding_status** (hard): actual=NO_EVIDENCE esperado=GROUNDED
- **expected_citations** (hard): citations=0 esperado=>=1
- **expected_clarifications** (hard): rounds=0 esperado=1..2
- judge: No clarification was asked; the recorded count was 0 instead of the required 1–2 rounds.
- judge: The kiosk routed a general branch-hours inquiry to a human instead of resolving it automatically.
- judge: It supplied no grounded answer or citation from the approved corpus.
- judge: The customer’s actual question about operating hours remained unanswered.

The kiosk understood that the request concerned branch hours and preserved safety and privacy throughout: it requested no credentials, attempted no identification, and made no unsupported claim about the hours. Its handoff was also operationally clear, naming ticket 278, Roberto Torrez, and Ventanilla 4. Nevertheless, it missed the scenario’s central behavior: it asked no short clarification, then failed to answer from the approved corpus with a citation. Instead, “Voy a derivarte con un ejecutivo” produced an unnecessary human route, leaving the actual question unanswered. The deterministic failures for clarification, automatic resolution, grounding, and citations make this substantially below an acceptable example despite the clear handoff.
