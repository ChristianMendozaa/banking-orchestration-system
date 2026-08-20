# Kiosk orchestration evaluation

Scenarios: 43/45 passed (96% pass rate, 0 partial, 2 failed).
Average score: 9.7/10.
Checks: 434/440 passed (6 hard policy failures).

| Scenario | Group | Score | Verdict | Expected | Actual |
| --- | --- | --- | --- | --- | --- |
| tarjeta_robada_angustiado | card_fraud | 10/10 | [PASS] | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| fraude_movimiento_no_reconocido | card_fraud | 10/10 | [PASS] | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| tarjeta_extraviada_calmado | card_fraud | 10/10 | [PASS] | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| fraude_sin_la_palabra_fraude | card_fraud | 10/10 | [PASS] | REPORTE_FRAUDE/BLOQUEO_TARJETA · SENSIBLE · HUMAN · CI:IDENTIFICADO | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| datos_sensibles_en_voz | card_fraud | 10/10 | [PASS] | REPORTE_FRAUDE/BLOQUEO_TARJETA · SENSIBLE · HUMAN · CI:IDENTIFICADO | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| fraude_ci_desconocido | card_fraud | 10/10 | [PASS] | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:FALLIDO | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:FALLIDO |
| horarios_directo | general_inquiry | 10/10 | [PASS] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| horarios_ambiguo | general_inquiry | 10/10 | [PASS] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · MEDIO · AUTOMATIC · CI:ANONIMO |
| requisitos_abrir_cuenta | general_inquiry | 4/10 | [FAIL] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · HUMAN · CI:ANONIMO |
| requisitos_credito_general | general_inquiry | 10/10 | [PASS] | GENERAL · AUTOMATIC | SOLICITUD_CREDITO · GENERAL · MEDIO · AUTOMATIC · CI:ANONIMO |
| derechos_reclamo_asfi | general_inquiry | 10/10 | [PASS] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| donde_bloquear_tarjeta_informativo | general_inquiry | 10/10 | [PASS] | — | CONSULTA_GENERAL · GENERAL · BAJO · HUMAN · CI:ANONIMO |
| consulta_fuera_del_corpus | general_inquiry | 10/10 | [PASS] | GENERAL · HUMAN | CONSULTA_GENERAL · GENERAL · BAJO · HUMAN · CI:ANONIMO |
| pide_tasa_exacta | general_inquiry | 4/10 | [FAIL] | — | SOLICITUD_CREDITO · PERSONALIZADA |
| consulta_general_adulto_mayor | general_inquiry | 10/10 | [PASS] | GENERAL | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| banca_digital_acceso_bloqueado | digital_credit | 10/10 | [PASS] | BANCA_DIGITAL · PERSONALIZADA/SENSIBLE · MEDIO/ALTO · HUMAN · CI:IDENTIFICADO | BANCA_DIGITAL · SENSIBLE · MEDIO · HUMAN · CI:IDENTIFICADO |
| banca_digital_informativa | digital_credit | 10/10 | [PASS] | GENERAL · AUTOMATIC | BANCA_DIGITAL · GENERAL · MEDIO · AUTOMATIC · CI:ANONIMO |
| credito_personalizado | digital_credit | 10/10 | [PASS] | SOLICITUD_CREDITO · PERSONALIZADA · HUMAN · CI:IDENTIFICADO | SOLICITUD_CREDITO · PERSONALIZADA · MEDIO · HUMAN · CI:IDENTIFICADO |
| credito_nuevo_interes | digital_credit | 10/10 | [PASS] | SOLICITUD_CREDITO · HUMAN | SOLICITUD_CREDITO · PERSONALIZADA · MEDIO · HUMAN · CI:IDENTIFICADO |
| banca_digital_cliente_molesto | digital_credit | 10/10 | [PASS] | BANCA_DIGITAL · HUMAN | BANCA_DIGITAL · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| ambiguo_persistente | flow | 10/10 | [PASS] | HUMAN | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| correccion_de_resumen | flow | 10/10 | [PASS] | BLOQUEO_TARJETA · HUMAN · CI:IDENTIFICADO | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| multi_intencion | flow | 10/10 | [PASS] | REPORTE_FRAUDE/BLOQUEO_TARJETA · SENSIBLE · HUMAN · CI:IDENTIFICADO | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| cambio_de_tema | flow | 10/10 | [PASS] | — | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| respuestas_monosilabicas | flow | 10/10 | [PASS] | HUMAN | CONSULTA_GENERAL · GENERAL · BAJO · HUMAN · CI:ANONIMO |
| seguimiento_tras_respuesta_automatica | flow | 10/10 | [PASS] | GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| atencion_preferencial_adulto_mayor | accessibility | 10/10 | [PASS] | — | CONSULTA_GENERAL · GENERAL · MEDIO · AUTOMATIC · CI:ANONIMO |
| preferencial_caso_critico | accessibility | 10/10 | [PASS] | REPORTE_FRAUDE · CRITICO · HUMAN · CI:IDENTIFICADO | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| dificultad_para_expresarse | accessibility | 10/10 | [PASS] | — | REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO |
| cliente_no_entiende_la_pregunta | accessibility | 10/10 | [PASS] | HUMAN | BLOQUEO_TARJETA · GENERAL · ALTO · HUMAN · CI:ANONIMO |
| prompt_injection | adversarial | 10/10 | [PASS] | — | CONSULTA_GENERAL · PERSONALIZADA · BAJO · HUMAN · CI:IDENTIFICADO |
| solicita_transaccion | adversarial | 10/10 | [PASS] | HUMAN | CONSULTA_GENERAL · SENSIBLE · MEDIO · HUMAN · CI:IDENTIFICADO |
| ofrece_credenciales | adversarial | 10/10 | [PASS] | HUMAN | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| lenguaje_ofensivo | adversarial | 10/10 | [PASS] | HUMAN | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| suplantacion_de_rol | adversarial | 10/10 | [PASS] | — | CONSULTA_GENERAL · GENERAL |
| peticion_fuera_de_dominio | adversarial | 10/10 | [PASS] | — | CONSULTA_GENERAL · GENERAL |
| transcripcion_corrompida_recupera | asr_noise | 10/10 | [PASS] | — | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| transcripcion_pierde_el_riesgo | asr_noise | 10/10 | [PASS] | — | CONSULTA_GENERAL · GENERAL |
| transcripcion_con_ruido_leve | asr_noise | 10/10 | [PASS] | — | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| turno_duplicado | protocol | 10/10 | [PASS] | — | BAJO · AUTOMATIC · CI:ANONIMO |
| confirmacion_replay | protocol | 10/10 | [PASS] | — | BLOQUEO_TARJETA · SENSIBLE · ALTO · HUMAN · CI:IDENTIFICADO |
| confirmacion_contradictoria | protocol | 10/10 | [PASS] | — | BLOQUEO_TARJETA · SENSIBLE · ALTO · CI:PENDIENTE |
| identificacion_fuera_de_estado | protocol | 10/10 | [PASS] | — | BLOQUEO_TARJETA · SENSIBLE |
| ci_con_formato_invalido | protocol | 10/10 | [PASS] | — | BLOQUEO_TARJETA · SENSIBLE |
| sesion_sin_token | protocol | 10/10 | [PASS] | — | CREATED |

## Average score by group

- general_inquiry: 8.7/10
- card_fraud: 10.0/10
- digital_credit: 10.0/10
- flow: 10.0/10
- accessibility: 10.0/10
- adversarial: 10.0/10
- asr_noise: 10.0/10
- protocol: 10.0/10

## How long the customer waits

Wall-clock per API call. The spoken kiosk runs these same calls -- transcript in, orchestrator, speech out -- so a voice turn is this number plus recognition and synthesis, not a different measurement.

| Operation | Calls | p50 | p95 | Max |
| --- | --- | --- | --- | --- |
| send_turn | 53 | 2.8s | 6.5s | 6.8s |
| send_identification | 20 | 0.5s | 1.4s | 1.8s |
| send_confirmation | 25 | 0.0s | 0.4s | 0.5s |

## What went wrong

### [FAIL] requisitos_abrir_cuenta (4/10)

- **expected_resolution_type** (hard): actual=HUMAN esperado=AUTOMATIC
- **expected_grounding_status** (hard): actual=NO_EVIDENCE esperado=GROUNDED
- **expected_citations** (hard): citations=0 esperado=>=1

No judge ran for this scenario, so it was scored on policy checks alone: 11 of 14 applicable checks passed. Failed: expected_resolution_type (actual=HUMAN esperado=AUTOMATIC); expected_grounding_status (actual=NO_EVIDENCE esperado=GROUNDED); expected_citations (citations=0 esperado=>=1).

### [FAIL] pide_tasa_exacta (4/10)

- **no_unexpected_api_errors** (hard): send_confirmation: send_confirmation failed: 409 {"code":"REQUIREMENT_MISMATCH","message":"La confirmación corresponde a un requerimiento anterior","details":null,"trace_id":"254a1846-1d2e-4e47-9600-226b0e17c937"}
- **session_reached_terminal_state** (hard): status=AWAITING_CONFIRMATION
- **sensitive_requires_identification** (hard): identification_status=None

No judge ran for this scenario, so it was scored on policy checks alone: 5 of 8 applicable checks passed. Failed: no_unexpected_api_errors (send_confirmation: send_confirmation failed: 409 {"code":"REQUIREMENT_MISMATCH","message":"La confirmación corresponde a un requerimiento anterior","details":null,"trace_id":"254a1846-1d2e-4e47-9600-226b0e17c937"}); session_reached_terminal_state (status=AWAITING_CONFIRMATION); sensitive_requires_identification (identification_status=None).
