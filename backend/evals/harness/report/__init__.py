"""Report renderers for a finished evaluation run.

All three consume the same `list[ScenarioResult]` and add no judgement of their own:

- `markdown` -- the terminal/CI artifact, and what `make evals-live` prints.
- `json_report` -- the machine-readable dump, including full transcripts.
- `html` -- the dashboard.
"""

from harness.report import html, json_report, markdown

__all__ = ["html", "json_report", "markdown"]
