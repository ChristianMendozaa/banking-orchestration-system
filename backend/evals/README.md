# Kiosk orchestration evaluation harness

An [AutoGen](https://github.com/microsoft/autogen) agent plays a bank customer with a
specific situation and a specific way of speaking, drives a real kiosk session turn by turn
against a **live backend**, and the finished session is then scored twice: once by
deterministic policy checks, and once by a second AutoGen agent — the judge — that grades
the things a rule cannot see and explains itself in writing.

The output is a scorecard, a JSON dump, and an HTML dashboard.

## What the kiosk is being evaluated on

The kiosk takes one natural-language Spanish request and must land it in exactly one of two
places: an **evidence-grounded automatic answer** built from the approved corpus in
`doc/rag/`, or a **human handoff** with a ticket, a deterministic priority and a
skill-matched executive. Everything between those poles is policy it must not get wrong —
masking PII before any model call, at most `MAX_CLARIFICATIONS` questions before giving up
to a human, explicit confirmation of a summary the customer would recognise, protected
identification for personalised and sensitive cases, and never executing a transaction,
asking for a credential, or answering beyond the retrieved evidence.

The suite exists to find out where that breaks.

## Two scores, and why both

The previous version of this harness ran five personas against four deterministic checks
and reported **5/5 personas, 29/29 checks**. That number was close to meaningless:

- `n/a: no es un reporte de fraude` counted as a *passed* check, so a persona could pass
  four of its six checks without exercising anything.
- The identification happy path was never tested. The operational seed contains real
  identity-card numbers and no persona ever used one, so every sensitive persona ended
  `FALLIDO` and still scored green.
- `BANCA_DIGITAL`, preferential attention, the correction loop, and general inquiries with
  no evidence in the corpus had **no coverage at all**.
- Nothing measured whether the kiosk actually understood the person, whether the summary
  matched what they said, or whether the Spanish sounded like a bank employee.

So scoring now has two halves that do different jobs:

**Deterministic checks** (`evaluator.py`) answer everything decidable from recorded state.
Each carries a severity and an applicability flag, so a check that does not apply reports
as such instead of inflating the pass count. There is no LLM in that module and there never
will be — it mirrors the principle the real orchestrator applies to `PrioritizationAgent`
and `DerivationAgent`: plain Python where the check is a rule, not a judgement.

**The judge** (`judge.py`) scores five dimensions from 1 to 10 — understanding, routing,
policy compliance, communication, resolution quality — and writes the reasoning that goes
in the report. It is given the scenario's rubric, the full transcript, the final system
state and the deterministic results, and told explicitly that those results are ground
truth it may explain but not contradict.

**Policy outranks opinion.** Any failed HARD check caps the final score at **4/10**
regardless of what the judge thought, and the report shows both numbers plus the reason for
the cap. A session can be warm, fluent and reassuring and still have failed to take a fraud
report to `CRITICO`; a scheme where charm outranks policy would be worse than no scoring.

> This replaces the earlier "why one agent, not two" position. That argument was right
> about the *policy* checks and they are unchanged. It was wrong that everything worth
> measuring is objectively decidable — tone, comprehension and answer usefulness are not,
> and they are what a kiosk lives or dies on.

## Running it

Needs a live backend (`make services-up`, or your own dev server) and `OPENAI_API_KEY`.
Every run makes real, billed calls on three fronts: the simulated customer, the judge, and
the backend's own classification, embedding and retrieval.

```bash
cd backend/evals
uv sync

export OPENAI_API_KEY=...
uv run python -m harness --html            # 41 scenarios, dashboard at reports/latest.html
```

Or from the repository root, which reads `MAX_CLARIFICATIONS` and `RAG_MIN_SCORE` out of
`backend/.env` so the harness asserts against the thresholds the evaluated backend actually
runs with:

```bash
make evals-live
```

Exits non-zero if any scenario did not pass, so it still works as a manually triggered gate.

### Useful flags

| Flag | Effect |
| --- | --- |
| `--list` | Print the catalog and exit |
| `--scenario NAME` | Run one scenario (repeatable) |
| `--tag TAG` | Run one group, e.g. `--tag adversarial` (repeatable) |
| `--no-judge` | Deterministic checks only — free, and useful as a smoke test |
| `--repeat N` | Run the selection N times to see score variance |
| `--concurrency N` | Sessions in flight at once (default 4) |
| `--model` / `--judge-model` | Default `gpt-5.4-mini` for the customer, `gpt-5.4` for the judge |
| `--html [PATH]` / `--json-output PATH` / `--output PATH` | Dashboard, JSON dump, markdown scorecard |

`--max-clarifications` and `--rag-min-score` must match the evaluated backend's settings:
the harness asserts against them.

Every scenario is bounded by a wall-clock timeout (5 minutes for the conversation, 3 for
the judge). Neither the OpenAI client nor AutoGen bounds the total, and a single stalled
request would otherwise hold its concurrency slot for the rest of the run — an expensive
way to find out that one call hung. A timeout is a scored failure like any other, so the
remaining scenarios still report.

## The scenario catalog

41 scenarios in `harness/scenarios/`. A **scenario** is the test case; a **persona style**
is only how that customer speaks — distressed, terse, elderly, hostile, rambling — kept
separate so the same situation can be re-tested through a different mouth, which is what
makes `tarjeta_robada_angustiado` and `tarjeta_extraviada_calmado` a controlled comparison
rather than two unrelated tests.

Each scenario carries an `ExpectedOutcome`: the single source of truth for what "correct"
means here. The evaluator turns its fields into HARD checks and the judge receives the same
object as its rubric, so the definition never lives in two places. Fields left as `None`
mean "this scenario does not constrain it" and produce a not-applicable check rather than a
free pass.

| Group | Tag | What it covers |
| --- | --- | --- |
| Card & fraud | `card_fraud` | Priority floors, mandatory identification (with **real seeded CIs**), a card number spoken aloud that must never be echoed back, fraud phrased without the word "fraude", and an unknown CI degrading gracefully |
| General inquiry | `general_inquiry` | Grounded, cited answers from the corpus — and the two cases where the right answer is *not to answer*: a product absent from the corpus, and a demand for an exact interest rate |
| Digital & credit | `digital_credit` | The first `BANCA_DIGITAL` coverage in the suite, plus the GENERAL/PERSONALIZADA line tested from both sides in each category |
| Conversation flow | `flow` | The clarification limit, the correction loop (`confirmed=false`), a mid-session change of topic, multi-intent, monosyllabic dead ends |
| Accessibility | `accessibility` | Preferential attention raising priority — and correctly *not* raising it past `CRITICO` — plus comprehension of difficult speech |
| Adversarial | `adversarial` | Prompt injection, requests to move money, a volunteered PIN, hostility, claimed staff identity, out-of-domain requests |
| Protocol | `protocol` | State-machine guards driven straight at the API with no LLM customer |

The `protocol` group overlaps `backend/tests/test_kiosk_flow.py` by design and does not
replace it. What that suite cannot cover is the environment: it runs on in-memory SQLite
with a stubbed provider, so it never exercises the `SELECT ... FOR UPDATE` session lock or
real PostgreSQL transaction boundaries. The group is deliberately limited to the guards
where the storage engine is part of the behaviour.

## The dashboard

`reports/latest.html` — one self-contained file, no CDN, no remote asset, no network call.
It opens from `file://` and keeps working when mailed to someone months later.

- Headline tiles: scenarios, average score, pass rate, policy checks and how many scores
  were capped.
- Two inline-SVG charts: the score distribution, and average score per group so the weakest
  area is visible at a glance.
- One row per scenario — score, verdict, expected vs actual, and the opening of the
  reasoning. Click any row for the **full conversation** as a chat, the judge's complete
  reasoning, its per-dimension scores, and every policy check with its detail.
- Filter by group and outcome, search across reasoning, sort by score, and toggle the
  theme.

## Testing the harness

```bash
uv run pytest      # 145 tests, fully mocked -- no network, no key, no running backend
uv run ruff check .
```

Covers the REST client, transcript capture, every deterministic check, the score-capping
rules, the judge's dossier and its failure mode, all three renderers (including asserting
the dashboard is genuinely self-contained), the runner's crash containment, and the
catalog's structural integrity — the last of which is worth more than it sounds: a scenario
whose expected `IDENTIFICADO` refers to an identity-card number missing from the seed would
quietly test the `FALLIDO` path instead, and nobody would notice for the price of a full
billed run.

It never calls `agent.run()` or `judge.assess()` against a real model. The live command
above is the actual behavioural verification.

## Why this is a separate project

There is no hard dependency conflict — `autogen-agentchat` installs and imports cleanly
alongside `backend/`. It is kept separate so its coverage never counts against `backend/`'s
`fail_under=90` gate, and so it can only ever be triggered deliberately.

## CI

There is no CI workflow for the live evaluation, and there should not be: every run makes
real billed calls on both sides. Run it manually against a `docker compose` backend. The
hermetic `pytest` suite here does run on every PR.
