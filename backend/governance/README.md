# Knowledge governance crew

A three-agent [CrewAI](https://github.com/crewAIInc/crewAI) crew that reviews a knowledge
document and produces a proposal for a manager to approve — never applies anything itself.

| Agent | Job |
| --- | --- |
| Document Analyst | Proposes categories, section structure, a review-after date |
| Compliance Reviewer | Runs independently of the Analyst's output; can veto activation |
| Retrieval QA | Uses the MCP server's `search_knowledge` tool (native CrewAI MCP integration) to check whether realistic customer questions actually retrieve grounded evidence |

## Why this is a separate project, not part of `backend/`

Two independent, hard blockers:

1. **Dependency conflict.** CrewAI's dependency tree wants `mcp<2.0.0`; the MCP server in
   `backend/app/mcp_server` requires `mcp>=2.0.0`. They cannot share one `pyproject.toml`.
2. **Python version.** CrewAI pulls in `chromadb` → `pydantic.v1`, which does not import
   on Python 3.14 (`ConfigError: unable to infer type for attribute`, not just a warning).
   `backend/`'s CI matrix tests 3.12 and 3.14; this project is pinned to `<3.14` and is
   deliberately outside that matrix.

Because of this, the crew talks to the rest of the system only as an external client would:
authenticated REST for the backend API, MCP for read-only knowledge search. It has no
dependency on `backend/app` and no direct database access — see `crew/client.py`.

## Running it

Requires a manager account (the existing seeded one, `gerencia@bmsc.com.bo` locally, is
fine) and an OpenAI API key for `crewai`'s LLM calls (reads `OPENAI_API_KEY` from the
environment). There is no dedicated "service account" baked into seed data — you supply
whatever manager credentials you have.

```bash
cd backend/governance
uv sync

export OPENAI_API_KEY=...                                    # for the crew's LLM calls
export GOVERNANCE_API_BASE_URL=http://localhost:8000
export GOVERNANCE_MCP_URL=http://localhost:8100/mcp
export GOVERNANCE_MANAGER_EMAIL=gerencia@bmsc.com.bo
export GOVERNANCE_MANAGER_PASSWORD=...                        # your local SEED_MANAGER_PASSWORD

uv run python -m crew <document_id>
```

This logs in, downloads the document, extracts its text, runs the crew (real OpenAI API
calls — real cost), and submits the resulting proposal via
`POST /management/knowledge/documents/{id}/governance-proposals`. A manager reviews
proposals with `GET .../governance-proposals` and, if they agree, applies changes
manually through the existing `PATCH /management/knowledge/documents/{id}` endpoint —
nothing here mutates the document automatically.

## Testing

```bash
uv run pytest
```

Covers the REST client (mocked HTTP), PDF text extraction, the proposal-shaping logic,
and that the crew's agents/tasks/MCP wiring compile correctly. It does **not** call
`kickoff()` — that needs a real LLM API key and costs real money — so a live end-to-end
run (per "Running it" above) is the verification step for actual crew behavior.
