# Kiosk orchestration evaluation

Scenarios: 1/9 passed (11% pass rate, 0 partial, 8 failed).
Average score: 1.9/10.
Checks: 56/87 passed (31 hard policy failures).

| Scenario | Group | Score | Verdict | Expected | Actual |
| --- | --- | --- | --- | --- | --- |
| horarios_directo | general_inquiry | 9/10 | [PASS] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CONSULTA_GENERAL · GENERAL · BAJO · AUTOMATIC · CI:ANONIMO |
| horarios_ambiguo | general_inquiry | 1/10 | [FAIL] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CREATED |
| requisitos_abrir_cuenta | general_inquiry | 1/10 | [FAIL] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CREATED |
| requisitos_credito_general | general_inquiry | 1/10 | [FAIL] | GENERAL · AUTOMATIC | CREATED |
| derechos_reclamo_asfi | general_inquiry | 1/10 | [FAIL] | CONSULTA_GENERAL · GENERAL · AUTOMATIC | CREATED |
| donde_bloquear_tarjeta_informativo | general_inquiry | 1/10 | [FAIL] | — | CREATED |
| consulta_fuera_del_corpus | general_inquiry | 1/10 | [FAIL] | GENERAL · HUMAN | CREATED |
| pide_tasa_exacta | general_inquiry | 1/10 | [FAIL] | — | CREATED |
| consulta_general_adulto_mayor | general_inquiry | 1/10 | [FAIL] | GENERAL | CREATED |

## Average score by group

- general_inquiry: 1.9/10

## What went wrong

### [FAIL] horarios_ambiguo (1/10)

- **session_reached_terminal_state** (hard): status=CREATED
- **expected_category** (hard): actual=None esperado=CONSULTA_GENERAL
- **expected_consultation_level** (hard): actual=None esperado=GENERAL
- **expected_resolution_type** (hard): actual=None esperado=AUTOMATIC
- **expected_grounding_status** (hard): actual=None esperado=GROUNDED
- **expected_citations** (hard): citations=0 esperado=>=1
- **expected_clarifications** (hard): rounds=0 esperado=1..2
- judge: No response to the vague opener and no clarification question.
- judge: Session never reached a terminal state.
- judge: Required category, consultation level, and automatic resolution were not recorded.
- judge: No grounded answer or citation was provided.
- judge: Customer received no explanation of what happens next.

The kiosk did not engage with the session. The empty transcript means it never delivered the scenario’s essential first step—a brief second-person clarification—and the final state corroborates this with clarification_rounds=0 and session_status=CREATED. It then failed every substantive outcome check: no CONSULTA_GENERAL category, no GENERAL consultation level, no AUTOMATIC resolution, no GROUNDED answer, and no citation. The only positives are passive safety outcomes: it did not request credentials, expose data, or impose an unnecessary confirmation. Those do not compensate for leaving the customer without any response or next step.

### [FAIL] requisitos_abrir_cuenta (1/10)

- **session_reached_terminal_state** (hard): status=CREATED
- **expected_category** (hard): actual=None esperado=CONSULTA_GENERAL
- **expected_consultation_level** (hard): actual=None esperado=GENERAL
- **expected_resolution_type** (hard): actual=None esperado=AUTOMATIC
- **expected_grounding_status** (hard): actual=None esperado=GROUNDED
- **expected_citations** (hard): citations=0 esperado=>=1
- judge: The session did not reach a terminal state.
- judge: Category and consultation level were not assigned.
- judge: The required automatic, grounded answer was not produced.
- judge: No citation was provided.
- judge: The customer received no next-step guidance.

The kiosk never engaged with the request: the transcript is empty, final_answer_to_customer is null, and the session remained CREATED. Consequently, it did not classify the inquiry as CONSULTA_GENERAL/GENERAL, provide the required grounded automatic answer about identity documentation and additional support for foreigners or minors, or attach citations. Its only compliant behaviors were passive ones—it did not request credentials or identification, disclose sensitive information, invent financial facts, or ask an unnecessary confirmation—but these do not offset the complete service failure. A person at the kiosk would leave with no answer and no next step.

### [FAIL] requisitos_credito_general (1/10)

- **session_reached_terminal_state** (hard): status=CREATED
- **expected_consultation_level** (hard): actual=None esperado=GENERAL
- **expected_resolution_type** (hard): actual=None esperado=AUTOMATIC
- **expected_grounding_status** (hard): actual=None esperado=GROUNDED
- **expected_citations** (hard): citations=0 esperado=>=1
- judge: The session did not reach a terminal state.
- judge: The required GENERAL consultation level was never assigned.
- judge: No AUTOMATIC answer was delivered.
- judge: No grounding status or approved-corpus evidence was recorded.
- judge: No required citation was provided.

This session is a complete service failure. The transcript contains no kiosk words to quote or assess, and the final state confirms that the session never progressed beyond "CREATED." Although the kiosk did not request credentials or identification and correctly skipped confirmation for this public-information question, those are merely avoided harms: it never classified the inquiry as GENERAL, supplied the required automatic grounded answer, or cited an approved source. The customer would leave with no information about consumer-credit requirements and no indication of what happens next.

### [FAIL] derechos_reclamo_asfi (1/10)

- **session_reached_terminal_state** (hard): status=CREATED
- **expected_category** (hard): actual=None esperado=CONSULTA_GENERAL
- **expected_consultation_level** (hard): actual=None esperado=GENERAL
- **expected_resolution_type** (hard): actual=None esperado=AUTOMATIC
- **expected_grounding_status** (hard): actual=None esperado=GROUNDED
- **expected_citations** (hard): citations=0 esperado=>=1
- judge: Session did not reach a terminal state.
- judge: No answer was given to the customer.
- judge: Expected category and consultation level were not recorded.
- judge: Expected automatic, grounded resolution was not produced.
- judge: No required regulatory citation was supplied.

The kiosk effectively did not handle the session. There is no transcript response to quote, the final answer is null, and the session remained at CREATED. Consequently, it did not classify the request as CONSULTA_GENERAL/GENERAL, provide the expected AUTOMATIC and GROUNDED regulatory answer, cite Ley 393, or tell the customer where to escalate the concluded complaint and what rights apply. The only positive policy signals are passive ones: it requested no credentials, attempted no unnecessary identification, and did not add an improper confirmation step. Those points prevent additional privacy or confirmation violations, but they cannot make a complete non-response acceptable.

### [FAIL] donde_bloquear_tarjeta_informativo (1/10)

- **session_reached_terminal_state** (hard): status=CREATED
- judge: No response was given to the customer.
- judge: The session never reached a terminal state.
- judge: No category or consultation level was assigned.
- judge: Neither a grounded answer nor a human-routing ticket was produced.
- judge: The customer was given no indication of what would happen next.

The kiosk completely failed to handle the session. The transcript contains no kiosk words at all, and the final state remained CREATED, matching the failed hard check "session_reached_terminal_state." Either permitted reading could have worked—an immediate grounded answer as CONSULTA_GENERAL or a confirmed human handoff under a sensitive reading—but the kiosk chose neither. Although it avoided requesting credentials, exposing data, or falsely claiming a transaction, those checks passed only because it never engaged; the customer received no information and no actionable next step.

### [FAIL] consulta_fuera_del_corpus (1/10)

- **session_reached_terminal_state** (hard): status=CREATED
- **expected_consultation_level** (hard): actual=None esperado=GENERAL
- **expected_resolution_type** (hard): actual=None esperado=HUMAN
- judge: No kiosk response appears in the transcript.
- judge: The session never reached a terminal state and remained CREATED.
- judge: The request was not classified as GENERAL.
- judge: The unsupported request was not routed to a human.
- judge: No actionable ticket, priority, desk, or next-step explanation was provided.

The kiosk produced no spoken response and took no meaningful action. Although this avoided the scenario's most dangerous failure—fabricating cryptocurrency custody or minimum-investment details—and correctly produced no citations or identification attempt, passive silence is not successful handling. Ground truth shows three decisive hard failures: the session stayed CREATED, consultation_level remained None rather than GENERAL, and resolution_type remained None rather than HUMAN. The required outcome was a clear human handoff without invented facts; instead, there was no ticket, priority, desk, executive assignment, or customer-facing explanation. The person at the kiosk would leave with no answer and no knowledge of what happens next.

### [FAIL] pide_tasa_exacta (1/10)

- **session_reached_terminal_state** (hard): status=CREATED
- judge: The session remained in nonterminal status "CREATED," matching the failed hard check.
- judge: No answer explained that the rate depends on individual credit analysis.
- judge: No human handoff, ticket, priority, or desk was created.
- judge: The customer received no final response or next-step guidance.

The kiosk avoided the two principal content hazards—fabricating an interest-rate percentage and requesting unnecessary identification—but only because it never responded at all. The empty transcript, null final answer, absence of any routing information, and ground-truth hard failure "session_reached_terminal_state" show a complete service failure. The expected handling was to explain that the exact rate depends on individual credit analysis, or to confirm and route a handoff to a credit executive; neither occurred, leaving the customer without an answer or next step. There is no kiosk language to praise or criticize because no utterance was recorded.

### [FAIL] consulta_general_adulto_mayor (1/10)

- **session_reached_terminal_state** (hard): status=CREATED
- **expected_consultation_level** (hard): actual=None esperado=GENERAL
- judge: No response was produced.
- judge: The session did not reach a terminal state.
- judge: The consultation level was not set to GENERAL.
- judge: The customer received neither an evidence-grounded answer nor an actionable handoff.

The kiosk effectively did nothing: the transcript contains no response, the final answer is null, and the session remained at CREATED. It therefore failed the scenario’s central task of extracting the real question from a roundabout request and answering it clearly from the approved corpus. Although it caused no privacy or credential-request violation and correctly skipped confirmation for a general inquiry, those are only passive successes; the deterministic ground truth records hard failures for terminal completion and the expected GENERAL consultation level. The person at the kiosk would leave without the account requirements or any next step.
