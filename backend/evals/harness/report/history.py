"""Append-only run ledger, and the cross-run dashboard rendered from it.

Every `python -m harness` invocation that writes a JSON report also appends one line to
`reports/history.jsonl` -- summary numbers only, a few KB per run, small enough to
git-track even though the full per-run JSON/HTML (hundreds of KB, judge-model-dependent,
fully regenerable from a replayed run) are not. This is the point of a cheap eval suite:
not just a cheap run once, but a record of whether the kiosk is actually getting better
that survives every future overwrite of `latest.*`.

The dashboard here (`to_html`) is rebuilt from the ledger alone, so it can always be
regenerated with `--rebuild-index` even if every run directory were deleted.
"""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from harness.report.theme import STYLES, TOGGLE_SCRIPT
from harness.report.theme import e as _e
from harness.report.theme import status_class as _status_class
from harness.scenarios import GROUP_LABELS, GROUP_ORDER
from harness.scoring import ScenarioResult, group_averages, summarize

LEDGER_FILENAME = "history.jsonl"


def _git(*args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5, check=True
        )
        return completed.stdout.strip()
    except Exception:  # noqa: BLE001 - git absent or this isn't a repo; never fatal
        return None


def current_git_sha() -> str:
    return _git("rev-parse", "--short", "HEAD") or "unknown"


def working_tree_is_dirty() -> bool:
    return bool(_git("status", "--porcelain"))


def make_run_id(*, generated_at: datetime | None = None, git_sha: str | None = None) -> str:
    stamp = (generated_at or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{git_sha or current_git_sha()}"


def build_run_record(
    results: list[ScenarioResult],
    *,
    run_id: str,
    metadata: dict,
    git_sha: str,
    git_dirty: bool,
) -> dict:
    """The row appended to the ledger. `judge_model` is recorded per run -- and the
    dashboard marks where it changes -- because scores from a mini judge and a flagship
    judge are not the same measurement, and a trend line that pretends otherwise would be
    the harness lying about its own numbers."""
    summary = summarize(results, duration_seconds=metadata.get("duration_seconds", 0))
    judged = sum(1 for result in results if result.verdict is not None)
    return {
        "run_id": run_id,
        "generated_at": metadata.get("generated_at"),
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "customer_model": metadata.get("customer_model"),
        "judge_model": metadata.get("judge_model"),
        "judged_scenarios": judged,
        "scenarios_total": summary.total,
        "repeat": metadata.get("repeat", 1),
        "duration_seconds": metadata.get("duration_seconds", 0),
        "summary": {
            "scenarios_passed": summary.passed,
            "scenarios_partial": summary.partial,
            "scenarios_failed": summary.failed,
            "average_score": round(summary.average_score, 2),
            "pass_rate": round(summary.pass_rate, 1),
            "checks_total": summary.checks_total,
            "checks_passed": summary.checks_passed,
            "hard_failures": summary.hard_failures,
        },
        "by_group": {group: round(value, 2) for group, value in group_averages(results).items()},
        "scenarios": {
            result.scenario: {"status": result.status, "score": result.score} for result in results
        },
    }


def append_run(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_runs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    runs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            runs.append(json.loads(line))
    return runs


# --- rendering ------------------------------------------------------------------------

MAX_MATRIX_RUNS = 24  # widest the table can get before it stops being scannable


def _short_label(run: dict) -> str:
    generated = run.get("generated_at") or run["run_id"]
    return generated.split(" ")[0] if " " in generated else generated[:10]


def _judge_model_boundaries(runs: list[dict]) -> set[int]:
    """Indices where the judge model differs from the previous run -- marked on the trend
    charts so a score jump reads as 'we switched judges', not 'the kiosk got worse'."""
    boundaries = set()
    for index in range(1, len(runs)):
        if runs[index].get("judge_model") != runs[index - 1].get("judge_model"):
            boundaries.add(index)
    return boundaries


def _line_chart(
    runs: list[dict], *, value, y_max: float, y_suffix: str = "", height: int = 180
) -> str:
    """One measure over time, points at each run, a dashed marker at every judge-model
    change. Single hue, same as every other chart in this project -- there is only one
    series, so there is nothing for a second hue to distinguish."""
    if not runs:
        return '<p class="hint">No runs recorded yet.</p>'
    width = max(360, 60 * len(runs))
    left, right, top_pad, bottom = 34, 16, 14, 26
    plot_w = width - left - right
    plot_h = height - top_pad - bottom
    n = len(runs)
    step = plot_w / max(n - 1, 1)

    def xy(index: int) -> tuple[float, float]:
        x = left + step * index
        v = max(0.0, min(value(runs[index]), y_max))
        y = top_pad + plot_h - (plot_h * v / y_max if y_max else 0)
        return x, y

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Trend over time">']
    baseline = top_pad + plot_h
    for frac in (0, 0.5, 1):
        y = top_pad + plot_h - plot_h * frac
        parts.append(
            f'<line class="gridline" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick tabular" x="{left - 6}" y="{y + 3.5:.1f}" '
            f'text-anchor="end">{y_max * frac:.0f}{y_suffix}</text>'
        )
    for index in _judge_model_boundaries(runs):
        x, _ = xy(index)
        parts.append(
            f'<line class="milestone" x1="{x:.1f}" y1="{top_pad}" x2="{x:.1f}" y2="{baseline}"/>'
        )
    points = [xy(index) for index in range(n)]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}" for i, (x, y) in enumerate(points))
    parts.append(f'<path class="line" d="{path}"/>')
    for index, (x, y) in enumerate(points):
        run = runs[index]
        v = value(run)
        parts.append(
            f'<circle class="dot-marker" cx="{x:.1f}" cy="{y:.1f}" r="4">'
            f"<title>{_e(_short_label(run))}: {v:.1f}{y_suffix} "
            f"(judge {_e(run.get('judge_model') or 'disabled')})</title></circle>"
        )
    # Only label first/last/every-other tick to avoid an illegible pile of text on long runs.
    label_every = max(1, n // 8)
    for index in range(0, n, label_every):
        x, _ = xy(index)
        parts.append(
            f'<text class="tick" x="{x:.1f}" y="{baseline + 16}" '
            f'text-anchor="middle">{_e(_short_label(runs[index]))}</text>'
        )
    parts.append(
        f'<line class="axis" x1="{left}" y1="{baseline}" x2="{width - right}" y2="{baseline}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _group_trend(runs: list[dict]) -> str:
    """Per-group average score, most recent run, with a small sparkline of its history --
    small multiples rather than one crowded chart, since seven overlapping lines would be
    unreadable at this width."""
    if not runs:
        return ""
    latest = runs[-1]
    groups = [group for group in GROUP_ORDER if group in latest.get("by_group", {})]
    groups.extend(sorted(g for g in latest.get("by_group", {}) if g not in GROUP_ORDER))
    if not groups:
        return ""
    rows = []
    for group in groups:
        series = [run.get("by_group", {}).get(group) for run in runs]
        present = [(i, v) for i, v in enumerate(series) if v is not None]
        current = present[-1][1] if present else 0.0
        rows.append(
            f'<div class="group-row"><span class="group-name">'
            f"{_e(GROUP_LABELS.get(group, group))}</span>"
            f"{_sparkline(present, len(runs))}"
            f'<span class="group-value">{current:.1f}/10</span></div>'
        )
    return f'<div class="groups">{"".join(rows)}</div>'


def _sparkline(present: list[tuple[int, float]], total_runs: int, *, width=160, height=28) -> str:
    if not present:
        return f'<svg viewBox="0 0 {width} {height}"></svg>'
    left, right = 4, 4
    plot_w = width - left - right
    y_max = 10.0
    points = [
        (
            left + (plot_w * i / max(total_runs - 1, 1) if total_runs > 1 else plot_w / 2),
            height - 4 - (height - 8) * (v / y_max),
        )
        for i, v in present
    ]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}" for i, (x, y) in enumerate(points))
    last_x, last_y = points[-1]
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Trend across runs">'
        f'<path class="line" d="{path}"/>'
        f'<circle class="dot-marker" cx="{last_x:.1f}" cy="{last_y:.1f}" r="3"/>'
        f"</svg>"
    )


def _matrix(runs: list[dict], run_hrefs: dict[str, str]) -> str:
    """One row per scenario, one column per run: the part of this dashboard that actually
    shows improvement. 'Fixed in run 7 and stayed fixed' looks completely different here
    from 'flaky, flips every run' -- a pass-rate line alone cannot tell those apart."""
    if not runs:
        return '<p class="empty">No runs recorded yet.</p>'
    shown = runs[-MAX_MATRIX_RUNS:]
    scenario_order: list[str] = []
    seen = set()
    for run in shown:
        for name in run.get("scenarios", {}):
            if name not in seen:
                seen.add(name)
                scenario_order.append(name)
    scenario_order.sort()

    header_cells = "".join(
        f'<th class="run-col" title="{_e(run["run_id"])}">'
        f'<a href="{_e(run_hrefs.get(run["run_id"], "#"))}">{_e(_short_label(run))}</a></th>'
        for run in shown
    )
    body_rows = []
    for name in scenario_order:
        cells = []
        for run in shown:
            entry = run.get("scenarios", {}).get(name)
            if entry is None:
                cells.append(
                    '<td class="cell"><span class="swatch missing" title="not run"></span></td>'
                )
                continue
            status = entry.get("status", "FAIL")
            score = entry.get("score", "?")
            cells.append(
                f'<td class="cell"><span class="swatch {_status_class(status)}" '
                f'title="{_e(name)}: {status} ({score}/10)"></span></td>'
            )
        body_rows.append(f'<tr><td class="scenario-name">{_e(name)}</td>{"".join(cells)}</tr>')

    return (
        '<div class="matrix-wrap"><table class="matrix"><thead><tr><th></th>'
        f"{header_cells}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def _tiles(runs: list[dict]) -> str:
    if not runs:
        return ""
    latest = runs[-1]
    previous = runs[-2] if len(runs) > 1 else None
    summary = latest["summary"]

    def delta(key: str) -> str:
        if previous is None:
            return "first recorded run"
        change = summary[key] - previous["summary"][key]
        if abs(change) < 0.05:
            return "unchanged vs previous run"
        sign = "+" if change > 0 else ""
        return f"{sign}{change:.1f} vs previous run"

    tiles = [
        ("Runs recorded", f"{len(runs)}", f"since {_e(_short_label(runs[0]))}"),
        (
            "Latest pass rate",
            f'{summary["pass_rate"]:.0f}<span class="unit">%</span>',
            delta("pass_rate"),
        ),
        (
            "Latest average score",
            f'{summary["average_score"]:.1f}<span class="unit">/10</span>',
            delta("average_score"),
        ),
        (
            "Latest judge",
            _e(latest.get("judge_model") or "disabled"),
            f"customer {_e(latest.get('customer_model', 'n/a'))}",
        ),
    ]
    return "".join(
        f'<div class="tile"><div class="label">{_e(label)}</div>'
        f'<div class="value">{value}</div><div class="sub">{sub}</div></div>'
        for label, value, sub in tiles
    )


def to_html(runs: list[dict], *, run_hrefs: dict[str, str] | None = None) -> str:
    """`run_hrefs` maps a `run_id` to the relative path of that run's own dashboard
    (`runs/<id>/report.html`), so the matrix and the run list can link out to it."""
    run_hrefs = run_hrefs or {}
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    run_list = "".join(
        f'<li><a href="{_e(run_hrefs.get(run["run_id"], "#"))}">{_e(run["run_id"])}</a> — '
        f"{run['summary']['pass_rate']:.0f}% pass · {run['summary']['average_score']:.1f}/10 · "
        f"judge {_e(run.get('judge_model') or 'disabled')}</li>"
        for run in reversed(runs)
    )
    run_count_label = f"{len(runs)} run{'s' if len(runs) != 1 else ''} recorded"

    return f"""<title>Kiosk Evaluation History</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{STYLES}</style>
<div class="page">
  <header class="masthead">
    <div>
      <h1>Kiosk evaluation history</h1>
      <p class="meta">Generated {_e(generated)} · {run_count_label}</p>
    </div>
    <span class="spacer"></span>
    <button class="theme" type="button">Toggle theme</button>
  </header>

  <section class="kpis">{_tiles(runs)}</section>

  <section class="charts">
    <div class="card">
      <h2>Pass rate over time</h2>
      <p class="hint">Dashed lines mark a change of judge model.</p>
      {_line_chart(runs, value=lambda r: r["summary"]["pass_rate"], y_max=100, y_suffix="%")}
    </div>
    <div class="card">
      <h2>Average score over time</h2>
      <p class="hint">Out of 10, after policy caps. Dashed lines mark a judge-model change.</p>
      {_line_chart(runs, value=lambda r: r["summary"]["average_score"], y_max=10)}
    </div>
  </section>

  <section class="card" style="margin-top:12px;">
    <h2>Average score by group</h2>
    <p class="hint">Latest run's value, with its trend across all recorded runs.</p>
    {_group_trend(runs)}
  </section>

  <section class="card" style="margin-top:12px;">
    <h2>Scenario outcomes across runs</h2>
    <p class="hint">
      One row per scenario, one column per run (most recent {MAX_MATRIX_RUNS}). A scenario
      that stays green run after run is fixed; one that flips is unstable, not fixed.
    </p>
    {_matrix(runs, run_hrefs)}
  </section>

  <section class="card" style="margin-top:12px;">
    <h2>All runs</h2>
    <ul class="run-links">{run_list}</ul>
  </section>

  <footer class="note">
    Rebuilt from <code>reports/history.jsonl</code> after every run, or on demand with
    <code>--rebuild-index</code>. Scores are only comparable within the same judge model.
  </footer>
</div>
<script>{TOGGLE_SCRIPT}</script>
"""
