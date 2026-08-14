# Orchestration policy evaluation harness

An [AutoGen](https://github.com/microsoft/autogen) agent plays a customer with a
specific persona and situation, drives a real kiosk session turn by turn against a
**live backend**, and a deterministic evaluator scores the finished session against the
orchestration policy. Produces a scorecard, not a pass/fail on vibes.

## Why one agent, not two

The original idea was "two-agent conversation." What actually earns that framing is the
customer side: reacting to a clarification question, a confirmation request, or an
identification request — each next message genuinely depends on the *real* system's
previous response. That's AutoGen's `AssistantAgent` tool-calling loop applied to one
agent with three tools (`send_turn`, `send_confirmation`, `send_identification`) bound to
a live `ConversationSession`.

There's deliberately no second "Evaluator" AutoGen agent. Every check in
`harness/evaluator.py` — did a fraud report reach `CRITICO`? was a sensitive case
identified before it resolved? was every automatic answer cited? — is objectively
decidable from the system's own recorded state. Making that an LLM judgment call would
add cost and variance to a question that's a rule, not a call — the same principle the
real orchestrator already applies to `PrioritizationAgent` and `DerivationAgent`.

## Why this is a separate project

There's no *hard* dependency conflict forcing separation — `autogen-agentchat` was
confirmed to install and import cleanly on both 3.12 and 3.14, with no version conflicts
against `backend/`, before any code was written. It's kept separate anyway so its
coverage never counts against `backend/`'s `fail_under=90` gate, and so it runs as its
own manually-triggered CI job — every run makes real, billed OpenAI calls, so it must
never run on every PR.

## Running it

Needs a live backend (`docker compose up`, or your local dev server) and
`OPENAI_API_KEY` for the Simulated Customer's LLM calls.

```bash
cd backend/evals
uv sync

export OPENAI_API_KEY=...
uv run python -m harness --base-url http://localhost:8000 --output scorecard.md
```

Exits non-zero if any persona fails a check, so it works as a CI gate. `--max-clarifications`
defaults to 2 and must match the evaluated backend's `MAX_CLARIFICATIONS` setting.

## Personas

Five scenarios in `harness/personas.py`, each with its own expectations layered on top of
four checks every persona gets: fraud reaches `CRITICO`, clarifications stay within the
limit, sensitive/personalized cases get identified before resolving, and automatic
answers carry citations.

| Persona | Tests |
| --- | --- |
| `tarjeta_robada_angustiado` | Card block / fraud routing under distress |
| `fraude_movimiento_no_reconocido` | Fraud reaches `CRITICO` |
| `consulta_horarios_ambigua` | Clarification loop, grounded automatic resolution |
| `consulta_credito_personalizada` | Personalized request routes to a human |
| `ambiguo_persistente` | Clarification-limit exhaustion forces a human fallback |

## Testing

```bash
uv run pytest
```

Covers the REST client (mocked HTTP), session state tracking, every evaluator check, the
personas, the scorecard renderer, and that the agent's wiring (tools, system message)
compiles correctly. It does **not** call `agent.run()` — real LLM cost — so the "Running
it" command above, against a live backend, is the actual behavioral verification.

**This was verified live during development**: the REST client was driven directly (no
LLM) against a running `docker compose` backend for a general-inquiry scenario (grounded
automatic resolution with real citations) and a fraud scenario (`CRITICO` priority,
mandatory identification before resolving) — both matched the evaluator's checks exactly.

## CI

There is no CI workflow for the live evaluation -- each run makes real, billed OpenAI
calls on both sides (the simulated customer and the backend's own classification/RAG),
so it is run manually from a local machine against a `docker compose` backend using the
"Running it" command above, never from an automated trigger.
