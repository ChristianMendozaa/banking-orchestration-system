# Kiosk orchestration evaluation

Scenarios: 3/4 passed (75% pass rate, 0 partial, 1 failed).
Average score: 7.2/10.
Checks: 36/37 passed (1 hard policy failures).

| Scenario | Group | Score | Verdict | Expected | Actual |
| --- | --- | --- | --- | --- | --- |
| donde_bloquear_tarjeta_informativo | general_inquiry | 10/10 | [PASS] | — | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| cambio_de_tema | flow | 2/10 | [FAIL] | — | CONSULTA_GENERAL · GENERAL · BAJO · HUMAN · CI:ANONIMO |
| dificultad_para_expresarse | accessibility | 7/10 | [PASS] | — | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| transcripcion_corrompida_recupera | asr_noise | 10/10 | [PASS] | — | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |

## Average score by group

- flow: 2.0/10
- accessibility: 7.0/10
- general_inquiry: 10.0/10
- asr_noise: 10.0/10

## How long the customer waits

Wall-clock per API call. A voice turn also pays speech detection and text-to-speech on top of these numbers.

| Operation | Calls | p50 | p95 | Max |
| --- | --- | --- | --- | --- |
| send_turn | 3 | 3.6s | 7.1s | 7.1s |
| send_identification | 1 | 0.6s | 0.6s | 0.6s |
| send_confirmation | 1 | 0.0s | 0.0s | 0.0s |

## What went wrong

### [FAIL] cambio_de_tema (2/10)

- **followed_the_topic_change** (hard): categoria final=CONSULTA_GENERAL
- judge: Prematurely completed the session after the opening-hours question despite the customer signaling another problem.
- judge: Failed the ground-truth topic-change check and retained CONSULTA_GENERAL with BAJO priority.
- judge: Created a human handoff without the required confirmation.
- judge: Did not open or preserve a separate case for the customer’s additional need.

This session failed its central requirement. The customer signaled a second problem—“en realidad también tengo un problema”—but the kiosk immediately said “Voy a derivarte con un ejecutivo para atender tu consulta” and terminated the interaction as a low-priority general inquiry. That premature completion prevented the fixture from disclosing the stolen-card emergency and is consistent with the mandatory failed check, “followed_the_topic_change.” The kiosk also skipped confirmation before creating the human handoff. Its safety behavior was otherwise sound: it requested no credentials, echoed no sensitive data, invented no financial information, and provided an actionable ticket, executive, and desk. Those strengths do not compensate for routing the wrong need and leaving the urgent issue unhandled.
