"""Report renderers for a finished evaluation run.

The first three consume the same `list[ScenarioResult]` and add no judgement of their own:

- `markdown` -- the terminal/CI artifact, and what `make evals-live` prints.
- `json_report` -- the machine-readable dump, including full transcripts.
- `html` -- the per-run dashboard.

`history` is different: it consumes the ledger (`reports/history.jsonl`), not a single
run's results, and renders the cross-run trend dashboard.
"""

from harness.report import history, html, json_report, markdown

__all__ = ["history", "html", "json_report", "markdown"]
