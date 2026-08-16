"""The evaluation dashboard: one self-contained HTML file.

No CDN, no external stylesheet, no remote font, no fetch -- the file is meant to be
opened straight off disk from `file://` and to keep working when mailed to someone or
attached to a CI run months later. Charts are inline SVG generated here in Python;
the only JavaScript is client-side filtering of rows that are already in the document.

Chart design follows the project's data-visualisation rules:

- Both charts plot **one measure**, so both use a single hue for every bar rather than a
  value ramp. Colouring bars darker-where-bigger would double-encode length as hue and
  spend the only free channel on information the bar already shows.
- Bars are capped at 24px, square at the baseline with a 4px rounded data-end, separated
  by surface-coloured gaps rather than strokes. Gridlines and axes are solid hairlines one
  step off the surface.
- Text never wears the data colour. Verdict identity is carried by a coloured dot *beside*
  the words PASS / PARTIAL / FAIL, never by colour alone, and the status hues that fall
  below 3:1 on the light surface are only ever used as those dots -- never as text.
- Dark mode is a selected set of steps validated against the dark surface, declared under
  both the OS media query and an explicit `data-theme` stamp so the in-page toggle wins in
  either direction.
"""

from datetime import UTC, datetime

from harness.report.theme import STYLES, TOGGLE_SCRIPT
from harness.report.theme import e as _e
from harness.report.theme import nice_ceiling as _nice_ceiling
from harness.report.theme import status_class as _status_class
from harness.scenarios import GROUP_LABELS, GROUP_ORDER
from harness.scoring import ScenarioResult, group_averages, score_spreads, summarize

MAX_SCORE = 10

DIMENSION_LABELS = {
    "understanding": "Understanding",
    "routing": "Routing",
    "policy_compliance": "Policy compliance",
    "communication": "Communication",
    "resolution_quality": "Resolution quality",
}

SCRIPT = (
    TOGGLE_SCRIPT
    + """
(function () {
  var rows = Array.prototype.slice.call(document.querySelectorAll('tr.summary'));
  rows.forEach(function (row) {
    row.addEventListener('click', function () {
      var detail = row.nextElementSibling;
      if (detail && detail.classList.contains('detail')) {
        detail.hidden = !detail.hidden;
        row.setAttribute('aria-expanded', detail.hidden ? 'false' : 'true');
      }
    });
  });

  var group = 'all';
  var outcome = 'all';
  var query = '';

  function apply() {
    var visible = 0;
    rows.forEach(function (row) {
      var matchGroup = group === 'all' || row.dataset.group === group;
      var matchOutcome = outcome === 'all' || row.dataset.status === outcome;
      var matchQuery = !query || row.dataset.haystack.indexOf(query) !== -1;
      var show = matchGroup && matchOutcome && matchQuery;
      row.hidden = !show;
      var detail = row.nextElementSibling;
      if (detail && detail.classList.contains('detail') && !show) {
        detail.hidden = true;
        row.setAttribute('aria-expanded', 'false');
      }
      if (show) { visible += 1; }
    });
    document.querySelector('.empty').hidden = visible !== 0;
  }

  function bind(selector, handler) {
    var chips = Array.prototype.slice.call(document.querySelectorAll(selector));
    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        chips.forEach(function (other) { other.setAttribute('aria-pressed', 'false'); });
        chip.setAttribute('aria-pressed', 'true');
        handler(chip.dataset.value);
        apply();
      });
    });
  }

  bind('.chip[data-filter="group"]', function (value) { group = value; });
  bind('.chip[data-filter="outcome"]', function (value) { outcome = value; });

  document.querySelector('input[type="search"]').addEventListener('input', function (event) {
    query = event.target.value.toLowerCase();
    apply();
  });

  var body = document.querySelector('tbody');
  var ascending = false;
  document.querySelector('th.sortable').addEventListener('click', function () {
    ascending = !ascending;
    var pairs = rows.map(function (row) {
      return [row, row.nextElementSibling];
    });
    pairs.sort(function (a, b) {
      var delta = Number(a[0].dataset.score) - Number(b[0].dataset.score);
      return ascending ? delta : -delta;
    });
    pairs.forEach(function (pair) {
      body.appendChild(pair[0]);
      if (pair[1]) { body.appendChild(pair[1]); }
    });
  });
})();
"""
)


def _score_histogram(results: list[ScenarioResult]) -> str:
    """Column chart, one bar per possible score. Ordered scale on the x-axis, so the
    axis carries identity and the single hue carries nothing but 'this is the measure'."""
    counts = {score: 0 for score in range(1, MAX_SCORE + 1)}
    for result in results:
        counts[result.score] = counts.get(result.score, 0) + 1
    top = _nice_ceiling(max(counts.values()) if counts else 1)

    width, height = 520, 208
    left, right, top_pad, bottom = 30, 8, 14, 30
    plot_w = width - left - right
    plot_h = height - top_pad - bottom
    band = plot_w / MAX_SCORE
    bar_w = min(24.0, band - 8)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Distribution of final scores from 1 to 10">'
    ]
    for index in range(3):
        value = top * index / 2
        y = top_pad + plot_h - (plot_h * index / 2)
        parts.append(
            f'<line class="gridline" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick tabular" x="{left - 7}" y="{y + 3.5:.1f}" '
            f'text-anchor="end">{value:.0f}</text>'
        )
    baseline = top_pad + plot_h
    for score in range(1, MAX_SCORE + 1):
        count = counts[score]
        centre = left + band * (score - 0.5)
        label_y = baseline + 16
        parts.append(
            f'<text class="tick tabular" x="{centre:.1f}" y="{label_y}" '
            f'text-anchor="middle">{score}</text>'
        )
        if not count:
            continue
        bar_h = plot_h * count / top
        y = baseline - bar_h
        x = centre - bar_w / 2
        radius = min(4.0, bar_h)
        # Square at the baseline, 4px rounded data-end: drawn as a path rather than a
        # rect so only the top corners round.
        parts.append(
            f'<path class="bar" d="M{x:.1f} {baseline:.1f} '
            f"V{y + radius:.1f} Q{x:.1f} {y:.1f} {x + radius:.1f} {y:.1f} "
            f"H{x + bar_w - radius:.1f} Q{x + bar_w:.1f} {y:.1f} "
            f'{x + bar_w:.1f} {y + radius:.1f} V{baseline:.1f} Z">'
            f"<title>{count} scenario{'s' if count != 1 else ''} scored {score}/10</title>"
            f"</path>"
        )
        parts.append(
            f'<text class="cap" x="{centre:.1f}" y="{y - 5:.1f}" '
            f'text-anchor="middle">{count}</text>'
        )
    parts.append(
        f'<line class="axis" x1="{left}" y1="{baseline}" x2="{width - right}" y2="{baseline}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _group_chart(results: list[ScenarioResult]) -> str:
    """Horizontal bars: seven long category names, one measure, one hue."""
    averages = group_averages(results)
    groups = [group for group in GROUP_ORDER if group in averages]
    groups.extend(sorted(group for group in averages if group not in GROUP_ORDER))
    if not groups:
        return ""

    width = 520
    left, right, top_pad, bottom = 126, 30, 10, 26
    row_h, bar_h = 30, 16
    height = top_pad + row_h * len(groups) + bottom
    plot_w = width - left - right

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Average score by scenario group, out of 10">'
    ]
    axis_y = top_pad + row_h * len(groups)
    for tick in range(0, MAX_SCORE + 1, 2):
        x = left + plot_w * tick / MAX_SCORE
        parts.append(
            f'<line class="gridline" x1="{x:.1f}" y1="{top_pad}" x2="{x:.1f}" y2="{axis_y}"/>'
        )
        parts.append(
            f'<text class="tick tabular" x="{x:.1f}" y="{axis_y + 15}" '
            f'text-anchor="middle">{tick}</text>'
        )
    for index, group in enumerate(groups):
        average = averages[group]
        centre = top_pad + row_h * index + row_h / 2
        y = centre - bar_h / 2
        label = GROUP_LABELS.get(group, group)
        parts.append(
            f'<text class="tick" x="{left - 10}" y="{centre + 4:.1f}" '
            f'text-anchor="end">{_e(label)}</text>'
        )
        bar_w = plot_w * average / MAX_SCORE
        radius = min(4.0, bar_w)
        parts.append(
            f'<path class="bar" d="M{left} {y:.1f} H{left + bar_w - radius:.1f} '
            f"Q{left + bar_w:.1f} {y:.1f} {left + bar_w:.1f} {y + radius:.1f} "
            f"V{y + bar_h - radius:.1f} Q{left + bar_w:.1f} {y + bar_h:.1f} "
            f'{left + bar_w - radius:.1f} {y + bar_h:.1f} H{left} Z">'
            f"<title>{_e(label)}: {average:.1f} out of 10</title></path>"
        )
        parts.append(
            f'<text class="cap" x="{left + bar_w + 7:.1f}" '
            f'y="{centre + 4:.1f}">{average:.1f}</text>'
        )
    parts.append(f'<line class="axis" x1="{left}" y1="{top_pad}" x2="{left}" y2="{axis_y}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _tiles(summary, results: list[ScenarioResult]) -> str:
    capped = sum(1 for result in results if result.was_capped)
    tiles = [
        (
            "Scenarios evaluated",
            f"{summary.total}",
            f"{summary.passed} passed · {summary.partial} partial · {summary.failed} failed",
        ),
        (
            "Average score",
            f'{summary.average_score:.1f}<span class="unit">/10</span>',
            "after policy caps are applied",
        ),
        (
            "Pass rate",
            f'{summary.pass_rate:.0f}<span class="unit">%</span>',
            f"scored {7}/10 or better with no hard failure",
        ),
        (
            "Policy checks",
            f'{summary.checks_passed}<span class="unit">/{summary.checks_total}</span>',
            f"{summary.hard_failures} hard failures · {capped} scores capped",
        ),
    ]
    return "".join(
        f'<div class="tile"><div class="label">{_e(label)}</div>'
        f'<div class="value">{value}</div><div class="sub">{_e(sub)}</div></div>'
        for label, value, sub in tiles
    )


def _chat(result: ScenarioResult) -> str:
    if not result.exchanges:
        return '<p class="dim-why">No exchanges were recorded.</p>'
    bubbles = []
    for exchange in result.exchanges:
        if exchange.customer_text:
            bubbles.append(
                f'<div class="msg customer"><span class="who">Customer · '
                f"{_e(exchange.tool)}</span>{_e(exchange.customer_text)}</div>"
            )
        if exchange.kiosk_speech:
            bubbles.append(
                f'<div class="msg kiosk"><span class="who">Kiosk</span>'
                f"{_e(exchange.kiosk_speech)}</div>"
            )
        if exchange.error:
            bubbles.append(
                f'<div class="msg error"><span class="who">API error</span>'
                f"{_e(exchange.error)}</div>"
            )
    return f'<div class="chat">{"".join(bubbles)}</div>'


def _judgement(result: ScenarioResult) -> str:
    """The full reasoning, plus the judge's own bullet lists. The row above shows only
    the first few lines of this."""
    parts = [f'<h3>Why this score</h3><p class="verdict-text">{_e(result.reasoning)}</p>']
    verdict = result.verdict
    if verdict and verdict.failures:
        items = "".join(f"<li>{_e(failure)}</li>" for failure in verdict.failures)
        parts.append(f'<h3>What went wrong</h3><ul class="bullets">{items}</ul>')
    if verdict and verdict.strengths:
        items = "".join(f"<li>{_e(strength)}</li>" for strength in verdict.strengths)
        parts.append(f'<h3>What went well</h3><ul class="bullets">{items}</ul>')
    return "".join(parts)


def _dimensions(result: ScenarioResult) -> str:
    if not result.verdict:
        return ""
    rows = "".join(
        f'<div class="dim"><span class="dim-name">{_e(DIMENSION_LABELS[name])}</span>'
        f'<span class="dim-score">{dimension.score}/10</span>'
        f'<span class="dim-why">{_e(dimension.reasoning)}</span></div>'
        for name, dimension in result.verdict.dimensions.items()
    )
    return f'<h3>Judge scores by dimension</h3><div class="dims">{rows}</div>'


def _checks(result: ScenarioResult) -> str:
    if not result.checks:
        return ""
    items = []
    for check in sorted(
        result.checks, key=lambda item: (item.applicable and item.passed, not item.applicable)
    ):
        if not check.applicable:
            css, mark = "na", "–"
        elif check.passed:
            css, mark = "ok", "✓"
        elif check.severity == "SOFT":
            css, mark = "warn", "!"
        else:
            css, mark = "bad", "✗"
        severity = "" if check.severity == "HARD" else " (soft)"
        items.append(
            f'<li class="{css}"><span class="mark">{mark}</span>'
            f"<span><strong>{_e(check.name)}</strong>{severity} — "
            f'<span class="detail-text">{_e(check.detail)}</span></span></li>'
        )
    return f'<h3>Policy checks</h3><ul class="checks">{"".join(items)}</ul>'


def _rows(results: list[ScenarioResult]) -> str:
    rows = []
    for result in results:
        status = result.status
        haystack = " ".join(
            [
                result.scenario,
                result.group,
                result.description,
                " ".join(result.tags),
                result.reasoning,
            ]
        ).lower()
        capped = (
            f'<span class="capped">capped from {result.raw_score}</span>'
            if result.was_capped
            else ""
        )
        name = _e(result.scenario)
        if result.repetition > 1:
            name += f' <span class="capped">#{result.repetition}</span>'
        rows.append(
            f'<tr class="summary" data-group="{_e(result.group)}" '
            f'data-status="{status}" data-score="{result.score}" '
            f'data-haystack="{_e(haystack)}" aria-expanded="false" tabindex="0">'
            f'<td class="name">{name}'
            f'<span class="desc">{_e(result.description)}</span></td>'
            f'<td class="outcome">{_e(GROUP_LABELS.get(result.group, result.group))}</td>'
            f'<td class="score"><span class="value">{result.score}/10</span>{capped}</td>'
            f'<td><span class="verdict"><span class="dot {_status_class(status)}"></span>'
            f"{status}</span></td>"
            f'<td class="outcome">{_e(result.expected_summary)}<br>'
            f'<span class="capped">got: {_e(result.actual_summary)}</span></td>'
            f'<td class="reason"><span class="clamp">{_e(result.reasoning)}</span></td></tr>'
        )
        rows.append(
            f'<tr class="detail" hidden><td colspan="6"><div class="detail-inner">'
            f"<div><h3>Conversation</h3>{_chat(result)}</div>"
            f"<div>{_judgement(result)}{_dimensions(result)}{_checks(result)}</div>"
            f"</div></td></tr>"
        )
    return "".join(rows)


def _variance_card(results: list[ScenarioResult]) -> str:
    """Shown only for `--repeat` runs. A scenario that scores 9, 4, 8 across three runs is
    not a 7 -- it is unstable, and that instability is the finding."""
    spreads = score_spreads(results)
    if not spreads:
        return ""
    rows = "".join(
        f'<tr><td>{_e(item.scenario)}</td><td class="num">{item.runs}</td>'
        f'<td class="num">{item.mean:.1f}</td>'
        f'<td class="num">{item.lowest}–{item.highest}</td>'
        f'<td class="num">{item.spread}</td></tr>'
        for item in spreads
    )
    return (
        '<section class="card variance"><h2>Score variance across repetitions</h2>'
        '<p class="hint">Widest spread first. A wide spread means the outcome is not '
        "stable, which is itself a finding.</p>"
        "<table><thead><tr><th>Scenario</th><th>Runs</th><th>Mean</th><th>Range</th>"
        f"<th>Spread</th></tr></thead><tbody>{rows}</tbody></table></section>"
    )


def _filter_chips(results: list[ScenarioResult]) -> str:
    present = {result.group for result in results}
    groups = [group for group in GROUP_ORDER if group in present]
    groups.extend(sorted(group for group in present if group not in GROUP_ORDER))
    chips = [
        '<button class="chip" data-filter="group" data-value="all" '
        'aria-pressed="true">All groups</button>'
    ]
    chips.extend(
        f'<button class="chip" data-filter="group" data-value="{_e(group)}" '
        f'aria-pressed="false">{_e(GROUP_LABELS.get(group, group))}</button>'
        for group in groups
    )
    chips.append('<span class="spacer"></span>')
    for label, value, pressed in (
        ("All outcomes", "all", "true"),
        ("Passed", "PASS", "false"),
        ("Partial", "PARTIAL", "false"),
        ("Failed", "FAIL", "false"),
    ):
        chips.append(
            f'<button class="chip" data-filter="outcome" data-value="{value}" '
            f'aria-pressed="{pressed}">{label}</button>'
        )
    return "".join(chips)


def to_html(results: list[ScenarioResult], *, metadata: dict | None = None) -> str:
    metadata = metadata or {}
    summary = summarize(results, duration_seconds=metadata.get("duration_seconds", 0))
    generated = metadata.get("generated_at") or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    minutes, seconds = divmod(int(metadata.get("duration_seconds", 0)), 60)

    meta_bits = [
        f"Generated {_e(generated)}",
        f"backend <code>{_e(metadata.get('base_url', 'unknown'))}</code>",
        f"customer <code>{_e(metadata.get('customer_model', 'n/a'))}</code>",
        f"judge <code>{_e(metadata.get('judge_model') or 'disabled')}</code>",
        f"run time {minutes}m {seconds:02d}s",
    ]

    return f"""<title>Kiosk Evaluation Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{STYLES}</style>
<div class="page">
  <header class="masthead">
    <div>
      <h1>Kiosk orchestration evaluation</h1>
      <p class="meta">{" · ".join(meta_bits)}</p>
    </div>
    <span class="spacer"></span>
    <button class="theme" type="button">Toggle theme</button>
  </header>

  <section class="kpis">{_tiles(summary, results)}</section>

  <section class="charts">
    <div class="card">
      <h2>Score distribution</h2>
      <p class="hint">Scenarios per final score, after policy caps.</p>
      {_score_histogram(results)}
    </div>
    <div class="card">
      <h2>Average score by group</h2>
      <p class="hint">Out of 10. Lower bars are where the kiosk is weakest.</p>
      {_group_chart(results)}
    </div>
  </section>

  {_variance_card(results)}

  <div class="controls">
    <input type="search" placeholder="Search scenarios and reasoning…" aria-label="Search">
    {_filter_chips(results)}
  </div>

  <div class="table-wrap">
    <table>
      <colgroup>
        <col style="width: 24%"><col style="width: 10%"><col style="width: 9%">
        <col style="width: 9%"><col style="width: 19%"><col style="width: 29%">
      </colgroup>
      <thead>
        <tr>
          <th>Scenario</th>
          <th>Group</th>
          <th class="sortable" title="Click to sort by score">Score ↕</th>
          <th>Verdict</th>
          <th>Expected → actual</th>
          <th>Why</th>
        </tr>
      </thead>
      <tbody>{_rows(results)}</tbody>
    </table>
    <div class="empty" hidden>No scenarios match these filters.</div>
  </div>

  <footer class="note">
    Click any row to see the full conversation, the judge's per-dimension reasoning, and
    every policy check. A failed hard check caps the score at 4/10 regardless of the
    judge's opinion.
  </footer>
</div>
<script>{SCRIPT}</script>
"""


def write_html(path: str, results: list[ScenarioResult], *, metadata: dict | None = None) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(to_html(results, metadata=metadata))
