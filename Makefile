.DEFAULT_GOAL := help
.NOTPARALLEL:
.PHONY: help install \
	backend-lint backend-test backend-coverage transcript-fidelity \
	evals-lint evals-test evals-smoke evals-live evals-deep \
	evals-live-claude-code evals-live-codex \
	evals-retry evals-retry-claude-code evals-retry-codex \
	frontend-lint frontend-typecheck frontend-test frontend-build \
	contract \
	services-up services-down \
	backend-unit backend-functional backend-integration backend-regression backend-usability \
	evals-unit frontend-unit frontend-functional frontend-integration frontend-regression frontend-usability \
	unit-test functional-test integration-test regression-test usability-test \
	test lint check check-live evals-last-report \
	_functional-suites _unit-suites _integration-suites _regression-suites _usability-suites \
	_quality-gates _reset _summary _report-status

# bash, not the Make default /bin/sh, so run_suite can read PIPESTATUS -- needed to get a
# suite's real exit code past the `| tee` used to both stream its output live and capture
# it for the checks-count extraction below.
SHELL := /bin/bash
REPORT := .make-report.tsv

# Extra flags appended to every evals-* harness invocation below, e.g.
#   make evals-live-codex EVAL_ARGS="--only-failing reports/runs/<run_id>/report.json"
#   make evals-smoke EVAL_ARGS="--tag adversarial --repeat 3"
# `?=` so it's empty (a no-op) unless set on the command line; every evals-* target's own
# fixed flags ($(2) in run_evals) still apply, EVAL_ARGS is appended after them.
EVAL_ARGS ?=

# Every suite target writes one PASS/FAIL/SKIP row to $(REPORT) (group, name, status, duration,
# and a checks count pulled from the tool's own output where one exists -- pytest/vitest
# "N passed" lines, the evals scorecard's "M/N aprobadas" line), prints that result
# immediately, and exits with the suite's own status -- so `make backend-test` alone still
# fails correctly. The aggregates (test/lint/check below) invoke suites through a nested
# `$(MAKE) -k`, which keeps going past a failing target instead of aborting, so every
# suite still runs and every failure still surfaces in one pass.
#
# The count column exists because "11 passed" (11 suites) reads as suspiciously few next
# to a project with hundreds of individual tests -- the summary should make clear those 11
# rows are suites, not the tests themselves.
#
# No leading "@" here: this is $(call)ed both directly (where the calling recipe line's
# own "@" already suppresses echo) and nested inside evals-live's shell if/else, where an
# embedded "@" would reach the shell as literal text instead of being stripped by make.
define run_suite
start=$$(date +%s); \
printf '\n\033[1m==> %s\033[0m\n' "$(1)"; \
log=$$(mktemp); \
( $(2) ) 2>&1 | tee "$$log"; \
rc=$${PIPESTATUS[0]}; \
if [ $$rc -eq 0 ]; then status=PASS; color='\033[32m'; else status=FAIL; color='\033[31m'; fi; \
dur=$$(( $$(date +%s) - start )); \
case "$(1)" in \
	evals:live*|evals:smoke|evals:deep|evals:retry*) \
		count=$$(grep -oE 'checks [0-9]+/[0-9]+' "$$log" | tail -1 | grep -oE '/[0-9]+' | tr -d '/');; \
	backend:*|evals:*) \
		count=$$(grep -oE '[0-9]+ (passed|failed|error|skipped|xfailed|xpassed)' "$$log" | awk '{sum+=$$1} END {if (sum>0) print sum}');; \
	frontend:*) \
		count=$$(grep -E '^ *Tests ' "$$log" | grep -oE '[0-9]+ (passed|failed)' | awk '{sum+=$$1} END {if (sum>0) print sum}');; \
	*) \
		count="";; \
esac; \
rm -f "$$log"; \
printf '%s\t%s\t%s\t%s\t%s\n' "$(3)" "$(1)" "$$status" "$$dur" "$$count" >> $(REPORT); \
printf "$$color%-22s %-6s\033[0m %5ss  %s\n" "$(1)" "$$status" "$$dur" "$${count:+($$count checks)}"; \
[ "$$status" = PASS ]
endef

help: ## Show this help
	@echo "Usage: make <target>"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { printf "  %-16s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## Sync backend, evals, and frontend dependencies
	cd backend && uv sync
	cd backend/evals && uv sync
	cd frontend && pnpm install --frozen-lockfile

## --- Individual suites (each is safe to run on its own; none needs a running system
## except evals-live) ---

backend-lint: ## Ruff format check + lint (backend/)
	@$(call run_suite,backend:lint,cd backend && uv run ruff format --check . && uv run ruff check .,QUALITY GATES)

backend-test: ## pytest under coverage (backend/) -- hermetic, in-memory SQLite
	@$(call run_suite,backend:full,cd backend && uv run coverage run -m pytest -q,QUALITY GATES)

backend-coverage: ## Enforce backend's fail_under=90 coverage gate
	@$(call run_suite,backend:coverage,cd backend && uv run coverage report,QUALITY GATES)

transcript-fidelity: ## Check live voice sessions classified what the customer actually said
	@cd backend && PYTHONPATH=. uv run python scripts/check_transcript_fidelity.py

evals-lint: ## Ruff check (backend/evals/)
	@$(call run_suite,evals:lint,cd backend/evals && uv run ruff check .,QUALITY GATES)

evals-test: ## pytest, fully mocked -- no LLM calls (backend/evals/)
	@$(call run_suite,evals:full,cd backend/evals && uv run pytest -q,QUALITY GATES)

frontend-lint: ## eslint (frontend/)
	@$(call run_suite,frontend:lint,cd frontend && pnpm lint,QUALITY GATES)

frontend-typecheck: ## next typegen + tsc --noEmit (frontend/)
	@$(call run_suite,frontend:typecheck,cd frontend && pnpm typecheck,QUALITY GATES)

frontend-test: ## vitest with coverage thresholds (frontend/)
	@$(call run_suite,frontend:full,cd frontend && pnpm test:coverage,QUALITY GATES)

frontend-build: ## next build (frontend/)
	@$(call run_suite,frontend:build,cd frontend && pnpm build,QUALITY GATES)

contract: ## Regenerate the OpenAPI contract and fail on drift
	@$(call run_suite,contract,cd frontend && pnpm generate:api && git diff --exit-code -- openapi.json lib/generated-api.ts,QUALITY GATES)

## --- Required test categories. These use explicit pytest markers and Vitest tags. A test
## may intentionally belong to more than one category; the report counts executions, not
## unique tests. None of these commands needs Docker, a running backend, or an API key. ---

backend-unit:
	@$(call run_suite,backend:unit,cd backend && uv run pytest -q -m unit,UNIT TESTS)

backend-functional:
	@$(call run_suite,backend:functional,cd backend && uv run pytest -q -m functional,FUNCTIONAL TESTS)

backend-integration:
	@$(call run_suite,backend:integration,cd backend && uv run pytest -q -m integration,INTEGRATION TESTS)

backend-regression:
	@$(call run_suite,backend:regression,cd backend && uv run pytest -q -m regression,REGRESSION TESTS)

backend-usability:
	@$(call run_suite,backend:usability,cd backend && uv run pytest -q -m usability,USABILITY TESTS)

evals-unit:
	@$(call run_suite,evals:unit,cd backend/evals && uv run pytest -q -m unit,UNIT TESTS)

frontend-unit:
	@$(call run_suite,frontend:unit,cd frontend && pnpm exec vitest run --tagsFilter unit,UNIT TESTS)

frontend-functional:
	@$(call run_suite,frontend:functional,cd frontend && pnpm exec vitest run --tagsFilter functional,FUNCTIONAL TESTS)

frontend-integration:
	@$(call run_suite,frontend:integration,cd frontend && pnpm exec vitest run --tagsFilter integration,INTEGRATION TESTS)

frontend-regression:
	@$(call run_suite,frontend:regression,cd frontend && pnpm exec vitest run --tagsFilter regression,REGRESSION TESTS)

frontend-usability:
	@$(call run_suite,frontend:usability,cd frontend && pnpm exec vitest run --tagsFilter usability,USABILITY TESTS)

services-up: ## Start postgres/redis/clamav/backend via docker compose
	docker compose up -d --wait backend

services-down: ## Stop docker compose services
	docker compose down

# Shared by evals-smoke/evals-live/evals-deep -- the three differ only in $(2), the judge
# mode passed to the harness. The harness must be told the same MAX_CLARIFICATIONS and
# RAG_MIN_SCORE the evaluated backend runs with -- they are policy thresholds it asserts
# against, not preferences -- so both are read from backend/.env rather than duplicated as
# constants here. Every invocation is recorded to reports/history.jsonl regardless of
# mode, so evals:smoke and evals:deep runs show up in the trend dashboard too.
#
# No leading "@" here, same reasoning as run_suite above: this is $(call)ed after a literal
# "@" already written at each call site below, so an embedded one here would reach the
# shell as literal text instead of being stripped by make.
define run_evals
openai_key=$$(grep -m1 '^OPENAI_API_KEY=' backend/.env 2>/dev/null | cut -d= -f2-); \
max_clar=$$(grep -m1 '^MAX_CLARIFICATIONS=' backend/.env 2>/dev/null | cut -d= -f2-); \
rag_min=$$(grep -m1 '^RAG_MIN_SCORE=' backend/.env 2>/dev/null | cut -d= -f2-); \
backend_port=$$(grep -m1 '^BACKEND_PORT=' .env 2>/dev/null | cut -d= -f2-); \
max_clar=$${max_clar:-2}; \
rag_min=$${rag_min:-0.45}; \
backend_port=$${backend_port:-8000}; \
if [ -z "$$openai_key" ]; then \
	printf '\n\033[1m==> $(1)\033[0m\n'; \
	echo "OPENAI_API_KEY not set in backend/.env -- skipping (harness and knowledge-bootstrap both need it)"; \
	printf '%s\t%s\t%s\t%s\t%s\n' "$(3)" "$(1)" "SKIP" "0" "" >> $(REPORT); \
else \
	$(call run_suite,$(1),docker compose up -d --build --wait backend && (cd backend && PYTHONPATH=. uv run python scripts/reset_kiosk_queue.py) && cd backend/evals && OPENAI_API_KEY="$$openai_key" uv run python -m harness --base-url http://localhost:$$backend_port --max-clarifications $$max_clar --rag-min-score $$rag_min --output scorecard.md $(2) $(EVAL_ARGS),$(3)); \
fi
endef

evals-smoke: ## Live catalog without LLM judge -- still needs Docker and billed backend/customer calls
	@$(call run_evals,evals:smoke,--no-judge,LIVE EVALUATION)

evals-live: ## Full catalog, mini judge (default) -- billed, but ~90% cheaper than evals-deep's judge
	@$(call run_evals,evals:live,,LIVE EVALUATION)

evals-deep: ## Full catalog, flagship judge -- billed at the harness's original (pre-cost-cut) rate
	@$(call run_evals,evals:deep,--judge-model gpt-5.4,LIVE EVALUATION)

# Full customer + judge eval on a local CLI instead of OpenAI -- billed against whatever
# that CLI is authenticated as on this machine, not OPENAI_API_KEY. OPENAI_API_KEY is
# still used for one thing in every mode: the kiosk backend under test itself
# (classification/RAG/embeddings) -- that's the system being evaluated, not something
# these providers stand in for. See
# backend/evals/README.md#running-on-a-local-cli-instead-of-openai.
evals-live-claude-code: ## Full catalog, customer + judge on the local `claude` CLI instead of OpenAI
	@$(call run_evals,evals:live-claude-code,--model claude-code --judge-model claude-code --concurrency 4,LIVE EVALUATION)

evals-live-codex: ## Full catalog, customer + judge on the local `codex` CLI instead of OpenAI
	@$(call run_evals,evals:live-codex,--model codex --judge-model codex --concurrency 4,LIVE EVALUATION)

# --only-failing reads a prior JSON report and runs (or --rejudge's) just the scenarios
# that were not PASS in it. There's no reports/latest.json alias (see cli.py::_record_run),
# so LATEST_RUN_REPORT resolves it by listing reports/runs/ -- names are
# %Y%m%dT%H%M%SZ-<sha>, so a plain sort is chronological -- and taking the newest. Runs
# inside run_evals's shell chain, after "cd backend/evals", so the path is relative to
# there, not the repo root. Point at a specific run's report instead with EVAL_ARGS, e.g.
#   make evals-retry EVAL_ARGS="--only-failing reports/runs/<run_id>/report.json"
LATEST_RUN_REPORT = reports/runs/$$(ls -1 reports/runs 2>/dev/null | sort | tail -1)/report.json

evals-retry: ## Re-run only the scenarios that weren't PASS in the most recent run, mini judge
	@$(call run_evals,evals:retry,--only-failing $(LATEST_RUN_REPORT),LIVE EVALUATION)

evals-retry-claude-code: ## Re-run only the scenarios that weren't PASS in the most recent run, customer + judge on `claude`
	@$(call run_evals,evals:retry-claude-code,--model claude-code --judge-model claude-code --concurrency 4 --only-failing $(LATEST_RUN_REPORT),LIVE EVALUATION)

evals-retry-codex: ## Re-run only the scenarios that weren't PASS in the most recent run, customer + judge on `codex`
	@$(call run_evals,evals:retry-codex,--model codex --judge-model codex --concurrency 4 --only-failing $(LATEST_RUN_REPORT),LIVE EVALUATION)

## --- Aggregates. Each runs its suites through a nested `make -k` (keep-going): every
## suite runs even if an earlier one fails, and every failure ends up in the summary. ---

define run_aggregate
	@$(MAKE) --no-print-directory _reset
	-@$(MAKE) --no-print-directory -k $(1)
	@$(MAKE) --no-print-directory _summary
endef

_unit-suites: backend-unit evals-unit frontend-unit
_functional-suites: backend-functional frontend-functional
_integration-suites: backend-integration frontend-integration
_regression-suites: backend-regression frontend-regression
_usability-suites: backend-usability frontend-usability

unit-test: ## Free isolated backend, frontend, and mocked-harness component tests
	$(call run_aggregate,_unit-suites)

functional-test: ## Free critical user and system-requirement flows
	$(call run_aggregate,_functional-suites)

integration-test: ## Free collaboration tests across local application layers
	$(call run_aggregate,_integration-suites)

regression-test: ## Free preserved bug fixes and stable critical flows
	$(call run_aggregate,_regression-suites)

usability-test: ## Free automated accessibility and clarity support checks; not participant research
	$(call run_aggregate,_usability-suites)

test: ## Fast, free, hermetic full suites only -- nothing needs to be running
	@$(MAKE) --no-print-directory _reset
	-@$(MAKE) --no-print-directory -k backend-test backend-coverage evals-test frontend-test
	@$(MAKE) --no-print-directory _summary

lint: ## All linters
	@$(MAKE) --no-print-directory _reset
	-@$(MAKE) --no-print-directory -k backend-lint evals-lint frontend-lint
	@$(MAKE) --no-print-directory _summary

_quality-gates: backend-lint backend-test backend-coverage evals-lint frontend-lint frontend-typecheck frontend-test frontend-build contract

evals-last-report: ## Print saved metrics from the latest live evaluation; never runs the harness
	@cd backend/evals && uv run python -m harness.report.latest

check: ## All free automated categories and quality gates; never Docker, an API key, or live evals
	@$(MAKE) --no-print-directory _reset
	-@$(MAKE) --no-print-directory -k _functional-suites _unit-suites _integration-suites _regression-suites _usability-suites _quality-gates
	@$(MAKE) --no-print-directory _summary SUMMARY_FAIL=false
	@$(MAKE) --no-print-directory evals-last-report
	@$(MAKE) --no-print-directory _report-status

check-live: ## Deliberate maximum validation: free check, then billed live evals
	@echo "WARNING: check-live runs the live LLM evaluation and can incur API or CLI-provider cost."
	@$(MAKE) --no-print-directory check
	-@$(MAKE) --no-print-directory evals-live
	@$(MAKE) --no-print-directory _summary SUMMARY_FAIL=false
	@$(MAKE) --no-print-directory evals-last-report
	@$(MAKE) --no-print-directory _report-status

_reset:
	@rm -f $(REPORT)
	@touch $(REPORT)

_summary:
	@awk -F'\t' ' \
		{ \
			group = $$1; \
			name = $$2; \
			status = $$3; \
			if (group != previous_group) { \
				printf "\n\033[1m%s\033[0m\n", group; \
				previous_group = group; \
			} \
			if (status == "PASS") { pass++; color = "\033[32m" } \
			else if (status == "SKIP") { skip++; color = "\033[33m" } \
			else { fail++; color = "\033[31m" } \
			total += $$4; \
			checks = $$5; \
			if (checks != "") { checks_total += checks; suites_with_checks++ } \
			label = (checks != "") ? checks " checks" : "-"; \
			printf "  %-20s %s%-6s\033[0m %5ss  %s\n", name, color, status, $$4, label; \
		} \
		END { \
			printf "\n%d suites: %d passed, %d failed, %d skipped   %ds total\n", \
				pass + fail + skip, pass, fail, skip, total; \
			if (suites_with_checks > 0) { \
				printf "%d individual tests/checks across %d suites (the rest are lint/build/typecheck gates without a per-item count)\n", \
					checks_total, suites_with_checks; \
			} \
			printf "Category counts can overlap: one test may provide evidence for more than one required category.\n"; \
			if (fail > 0 && "$(SUMMARY_FAIL)" != "false") exit 1; \
		} \
	' $(REPORT)

_report-status:
	@awk -F'\t' '$$3 == "FAIL" { exit 1 }' $(REPORT)
