"""Visual system shared by the per-run dashboard (`html.py`) and the cross-run history
dashboard (`history.py`), so the two pages read as one product rather than two.

Extracted rather than duplicated: colours, spacing and the escaping/formatting helpers
live here once. Page-specific markup (the per-run table, the history matrix) stays in
its own module.
"""

import html as html_escape

STYLES = """
:root {
  color-scheme: light;
  --page: #f9f9f7;
  --surface: #fcfcfb;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11, 11, 11, 0.10);
  --bar: #2a78d6;
  --good: #0ca30c;
  --warning: #fab219;
  --critical: #d03b3b;
  --wash: rgba(11, 11, 11, 0.04);
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d;
    --surface: #1a1a19;
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255, 255, 255, 0.10);
    --bar: #3987e5;
    --wash: rgba(255, 255, 255, 0.05);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d;
  --surface: #1a1a19;
  --ink: #ffffff;
  --ink-2: #c3c2b7;
  --muted: #898781;
  --grid: #2c2c2a;
  --axis: #383835;
  --border: rgba(255, 255, 255, 0.10);
  --bar: #3987e5;
  --wash: rgba(255, 255, 255, 0.05);
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.page { max-width: 1180px; margin: 0 auto; padding: 32px 20px 72px; }

header.masthead { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
header.masthead h1 { font-size: 24px; margin: 0 0 6px; letter-spacing: -0.01em; }
.meta { color: var(--ink-2); font-size: 13px; margin: 0; }
.meta code { background: var(--wash); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.spacer { flex: 1 1 auto; }
button.theme {
  border: 1px solid var(--border); background: var(--surface); color: var(--ink-2);
  border-radius: 8px; padding: 7px 12px; font: inherit; font-size: 13px; cursor: pointer;
}
button.theme:hover { background: var(--wash); }

.kpis {
  display: grid; gap: 12px; margin: 28px 0 20px;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
}
.tile {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px 18px;
}
.tile .label { color: var(--ink-2); font-size: 12.5px; margin-bottom: 6px; }
.tile .value { font-size: 34px; line-height: 1.1; letter-spacing: -0.02em; }
.tile .value .unit { font-size: 16px; color: var(--muted); letter-spacing: 0; }
.tile .sub { color: var(--ink-2); font-size: 12px; margin-top: 4px; }

.charts { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px 18px 12px;
}
.card h2 { font-size: 14px; margin: 0 0 2px; font-weight: 600; }
.card p.hint { color: var(--ink-2); font-size: 12px; margin: 0 0 12px; }
.card svg { width: 100%; height: auto; display: block; }
.tick { fill: var(--muted); font-size: 11px; }
.tick.tabular { font-variant-numeric: tabular-nums; }
.cap { fill: var(--ink-2); font-size: 11px; font-variant-numeric: tabular-nums; }
.gridline { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--axis); stroke-width: 1; }
.bar { fill: var(--bar); }
.line { fill: none; stroke: var(--bar); stroke-width: 2; }
.dot-marker { fill: var(--surface); stroke: var(--bar); stroke-width: 2; }
.milestone { stroke: var(--axis); stroke-width: 1; stroke-dasharray: 3 3; }

.controls {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin: 28px 0 12px;
}
.controls input[type="search"] {
  flex: 1 1 220px; min-width: 180px;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink);
  border-radius: 8px; padding: 8px 11px; font: inherit; font-size: 13px;
}
.chip {
  border: 1px solid var(--border); background: var(--surface); color: var(--ink-2);
  border-radius: 999px; padding: 6px 13px; font: inherit; font-size: 13px; cursor: pointer;
}
.chip[aria-pressed="true"] {
  background: var(--ink); color: var(--surface); border-color: var(--ink);
}

table { width: 100%; border-collapse: collapse; table-layout: fixed; min-width: 900px; }
.table-wrap {
  overflow-x: auto; background: var(--surface);
  border: 1px solid var(--border); border-radius: 12px;
}
thead th {
  text-align: left; font-size: 12px; font-weight: 600; color: var(--ink-2);
  padding: 12px 14px; border-bottom: 1px solid var(--border); white-space: nowrap;
}
thead th.sortable { cursor: pointer; user-select: none; }
tbody td { padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
tbody tr.summary { cursor: pointer; }
tbody tr.summary:hover td { background: var(--wash); }
tbody tr.summary td.name { font-weight: 600; font-size: 13.5px; overflow-wrap: anywhere; }
tbody tr.summary td.name .desc {
  display: block; font-weight: 400; color: var(--ink-2);
  font-size: 12px; margin-top: 3px;
}
td.score { font-variant-numeric: tabular-nums; font-size: 15px; }
td.score .value { white-space: nowrap; }
td.outcome { font-size: 12px; color: var(--ink-2); overflow-wrap: anywhere; }
/* The full reasoning lives in the expanded panel; the row shows the opening so a
   reader can scan 41 rows without every one of them being a paragraph tall. */
td.reason { color: var(--ink-2); font-size: 13px; }
td.reason .clamp {
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 4;
  overflow: hidden;
}

.verdict {
  display: inline-flex; align-items: center; gap: 7px;
  white-space: nowrap; font-size: 12.5px;
}
.dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.dot.pass { background: var(--good); }
.dot.partial { background: var(--warning); }
.dot.fail { background: var(--critical); }
.capped { color: var(--ink-2); font-size: 11.5px; }
td.score .capped { display: block; margin-top: 2px; }

tr.detail > td { background: var(--wash); padding: 0 14px; }
tr.detail[hidden] { display: none; }
.detail-inner {
  display: grid; gap: 18px; padding: 18px 0 22px;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
}
@media (max-width: 820px) { .detail-inner { grid-template-columns: minmax(0, 1fr); } }
.detail h3 {
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--muted); margin: 0 0 10px; font-weight: 600;
}

.chat { display: flex; flex-direction: column; gap: 9px; }
.msg {
  max-width: 88%; padding: 9px 12px; border-radius: 12px;
  font-size: 13.5px; border: 1px solid var(--border);
}
.msg .who {
  display: block; font-size: 10.5px; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--muted); margin-bottom: 3px;
}
.msg.customer { align-self: flex-start; background: var(--surface); }
.msg.kiosk { align-self: flex-end; background: transparent; }
.msg.error { align-self: stretch; max-width: 100%; border-color: var(--critical); }

.dims { display: grid; gap: 9px; margin-bottom: 18px; }
.dim {
  display: grid; grid-template-columns: 148px 44px 1fr;
  gap: 10px; align-items: baseline; font-size: 13px;
}
.dim .dim-name { color: var(--ink-2); }
.dim .dim-score { font-variant-numeric: tabular-nums; }
.dim .dim-why { color: var(--ink-2); font-size: 12.5px; }

ul.checks {
  list-style: none; margin: 0; padding: 0;
  display: grid; gap: 6px; font-size: 12.5px;
}
ul.checks li { display: grid; grid-template-columns: 14px 1fr; gap: 8px; }
ul.checks li .mark { font-variant-numeric: tabular-nums; }
ul.checks li.ok .mark { color: var(--good); }
ul.checks li.bad .mark { color: var(--critical); }
ul.checks li.warn .mark { color: var(--warning); }
ul.checks li.na { color: var(--ink-2); opacity: 0.75; }
ul.checks li .detail-text { color: var(--ink-2); }
.verdict-text { font-size: 13px; color: var(--ink-2); margin: 0 0 18px; white-space: pre-wrap; }
ul.bullets { margin: 0 0 18px; padding-left: 18px; font-size: 12.5px; color: var(--ink-2); }
ul.bullets li { margin-bottom: 4px; }
.variance { margin-top: 12px; }
.variance table { table-layout: auto; min-width: 0; }
.variance thead th { padding: 8px 10px; }
.variance tbody td { padding: 8px 10px; font-size: 13px; }
.variance td.num { font-variant-numeric: tabular-nums; text-align: right; width: 80px; }
.empty { padding: 28px 14px; color: var(--ink-2); text-align: center; font-size: 13px; }
footer.note { color: var(--ink-2); font-size: 12px; margin-top: 22px; }

.matrix-wrap { overflow-x: auto; }
table.matrix { table-layout: auto; min-width: 0; border-collapse: separate; border-spacing: 3px; }
table.matrix th { font-size: 11px; white-space: nowrap; }
table.matrix th.run-col {
  writing-mode: vertical-rl; transform: rotate(180deg); text-align: left;
  padding: 4px 2px; font-variant-numeric: tabular-nums; max-width: 18px;
}
table.matrix td.scenario-name {
  font-size: 12px; white-space: nowrap; padding: 4px 10px 4px 0; text-align: right;
  color: var(--ink-2);
}
td.cell { padding: 0; border-bottom: none; }
.swatch {
  width: 16px; height: 16px; border-radius: 4px; margin: 0 auto;
}
.swatch.pass { background: var(--good); }
.swatch.partial { background: var(--warning); }
.swatch.fail { background: var(--critical); }
.swatch.missing { background: var(--wash); border: 1px dashed var(--border); }
.run-links { font-size: 12px; color: var(--ink-2); margin: 4px 0 0; }
.run-links a { color: inherit; }
.groups { display: grid; gap: 10px; margin-top: 8px; }
.group-row { display: grid; grid-template-columns: 150px 1fr 44px; align-items: center; gap: 12px; }
.group-row .group-name { font-size: 13px; color: var(--ink-2); }
.group-row .group-value { font-size: 13px; font-variant-numeric: tabular-nums; text-align: right; }
"""


TOGGLE_SCRIPT = """
(function () {
  var root = document.documentElement;
  var toggle = document.querySelector('button.theme');
  toggle.addEventListener('click', function () {
    var dark = root.getAttribute('data-theme') === 'dark' ||
      (!root.getAttribute('data-theme') &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);
    root.setAttribute('data-theme', dark ? 'light' : 'dark');
  });
})();
"""


def e(value: object) -> str:
    return html_escape.escape(str(value if value is not None else ""))


def status_class(status: str) -> str:
    return {"PASS": "pass", "PARTIAL": "partial", "FAIL": "fail"}.get(status, "fail")


def nice_ceiling(value: float) -> float:
    if value <= 5:
        return max(value, 1)
    step = 2 if value <= 20 else 5
    return ((int(value) + step - 1) // step) * step
