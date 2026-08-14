"""The three renderers.

The HTML test is the important one: the dashboard's whole promise is that it opens from
`file://` months later with no network, so "self-contained" is asserted rather than
assumed.
"""

import json
import re

from conftest import make_result

from harness.evaluator import CheckResult
from harness.report import html, json_report, markdown
from harness.scoring import ScenarioResult

HARD_FAIL = CheckResult("fraud_reaches_critical", False, "priority=ALTO")
SOFT_FAIL = CheckResult("routed_to_skilled_executive", False, "sin skill", severity="SOFT")
SKIPPED = CheckResult.skip("automatic_answers_are_cited", "no fue automatico")
PASSING = CheckResult("clarifications_bounded", True, "rounds=0")

METADATA = {
    "generated_at": "2026-08-14 18:00 UTC",
    "base_url": "http://localhost:8000",
    "customer_model": "gpt-5.4-mini",
    "judge_model": "gpt-5.4",
    "duration_seconds": 754,
}


def _results() -> list[ScenarioResult]:
    return [
        make_result(name="horarios_directo", group="general_inquiry", score=9, checks=[PASSING]),
        make_result(
            name="fraude_movimiento_no_reconocido",
            group="card_fraud",
            score=10,
            checks=[HARD_FAIL, SKIPPED],
        ),
        make_result(name="prompt_injection", group="adversarial", score=5, checks=[SOFT_FAIL]),
    ]


# --- markdown -----------------------------------------------------------------------


def test_markdown_reports_the_capped_score_not_the_judges() -> None:
    text = markdown.to_markdown(_results())
    assert "4/10" in text
    assert "1/3 passed" in text


def test_markdown_explains_every_scenario_that_did_not_pass() -> None:
    text = markdown.to_markdown(_results())
    assert "## What went wrong" in text
    assert "**fraud_reaches_critical** (hard)" in text
    assert "routed_to_skilled_executive (soft)" in text


def test_markdown_renders_an_empty_run() -> None:
    assert "0/0 passed" in markdown.to_markdown([])


# --- json ---------------------------------------------------------------------------


def test_json_keeps_both_the_raw_and_the_capped_score() -> None:
    payload = json_report.to_dict(_results(), metadata=METADATA)
    fraud = next(
        r for r in payload["results"] if r["scenario"] == "fraude_movimiento_no_reconocido"
    )
    assert fraud["raw_judge_score"] == 10
    assert fraud["score"] == 4
    assert fraud["score_cap_reason"] == "fraud_reaches_critical"


def test_json_includes_transcripts_and_dimension_scores() -> None:
    payload = json_report.to_dict(_results(), metadata=METADATA)
    first = payload["results"][0]
    assert first["transcript"][0]["customer"] == "Hola, quiero saber los horarios."
    assert set(first["judge"]["dimensions"]) == {
        "understanding",
        "routing",
        "policy_compliance",
        "communication",
        "resolution_quality",
    }


def test_json_marks_which_checks_did_not_apply() -> None:
    payload = json_report.to_dict(_results(), metadata=METADATA)
    fraud = next(
        r for r in payload["results"] if r["scenario"] == "fraude_movimiento_no_reconocido"
    )
    skipped = next(c for c in fraud["checks"] if c["name"] == "automatic_answers_are_cited")
    assert skipped["applicable"] is False


def test_json_output_is_serializable() -> None:
    json.dumps(json_report.to_dict(_results(), metadata=METADATA), ensure_ascii=False)


# --- html ---------------------------------------------------------------------------


def test_html_is_self_contained() -> None:
    """A strict reading: no remote asset of any kind, so the file works offline forever."""
    page = html.to_html(_results(), metadata=METADATA)
    for pattern in (
        r'src\s*=\s*["\']https?://',
        r'href\s*=\s*["\']https?://',
        r'@import\s+url\(\s*["\']?https?://',
        r"\bfetch\s*\(",
        r"XMLHttpRequest",
        r"new\s+WebSocket",
    ):
        assert not re.search(pattern, page), f"dashboard reaches out via {pattern}"


def test_html_carries_the_run_metadata() -> None:
    page = html.to_html(_results(), metadata=METADATA)
    assert "gpt-5.4-mini" in page
    assert "http://localhost:8000" in page
    assert "12m 34s" in page


def test_html_shows_the_headline_numbers() -> None:
    page = html.to_html(_results(), metadata=METADATA)
    assert "Average score" in page
    assert "6.0" in page  # (9 + 4 + 5) / 3
    assert "Pass rate" in page


def test_html_shows_the_reasoning_and_the_cap() -> None:
    page = html.to_html(_results(), metadata=METADATA)
    assert "capped from 10" in page
    assert "Score capped at 4/10" in page


def test_html_includes_the_conversation_and_the_checks() -> None:
    page = html.to_html(_results(), metadata=METADATA)
    assert "Hola, quiero saber los horarios." in page
    assert "clarifications_bounded" in page
    assert "Judge scores by dimension" in page


def test_html_escapes_content_rather_than_letting_it_break_the_page() -> None:
    hostile = make_result(
        name="<img src=x onerror=alert(1)>",
        checks=[CheckResult("x", False, "<script>alert(2)</script>")],
    )
    page = html.to_html([hostile], metadata=METADATA)
    assert "<img src=x" not in page
    assert "<script>alert(2)</script>" not in page
    assert "&lt;script&gt;" in page


def test_html_declares_dark_mode_under_both_scopes() -> None:
    """The OS media query covers the system setting; the data-theme scope lets the in-page
    toggle win in either direction."""
    page = html.to_html(_results(), metadata=METADATA)
    assert "@media (prefers-color-scheme: dark)" in page
    assert ':root[data-theme="dark"]' in page
    assert ':root:where(:not([data-theme="light"]))' in page


def test_html_charts_use_one_hue_for_every_bar() -> None:
    """Two single-measure charts: colouring bars darker-where-bigger would double-encode
    length as hue."""
    page = html.to_html(_results(), metadata=METADATA)
    fills = set(re.findall(r'<path class="(bar)"', page))
    assert fills == {"bar"}


def test_html_renders_an_empty_run_without_crashing() -> None:
    page = html.to_html([], metadata=METADATA)
    assert "No scenarios match these filters." in page


def test_write_html_produces_a_titled_file(tmp_path) -> None:
    target = tmp_path / "report.html"
    html.write_html(str(target), _results(), metadata=METADATA)
    assert target.read_text(encoding="utf-8").startswith("<title>")


# --- score variance (--repeat runs) -------------------------------------------------


def _repeated() -> list[ScenarioResult]:
    return [
        make_result(name="horarios_directo", score=9, checks=[PASSING], repetition=1),
        make_result(name="horarios_directo", score=4, checks=[PASSING], repetition=2),
        make_result(name="horarios_directo", score=8, checks=[PASSING], repetition=3),
        make_result(name="prompt_injection", score=8, checks=[PASSING], repetition=1),
        make_result(name="prompt_injection", score=8, checks=[PASSING], repetition=2),
    ]


def test_variance_is_reported_only_for_scenarios_run_more_than_once() -> None:
    from harness.scoring import score_spreads

    spreads = score_spreads(_repeated() + [make_result(name="once", checks=[PASSING])])
    assert [item.scenario for item in spreads] == ["horarios_directo", "prompt_injection"]
    assert spreads[0].mean == 7.0
    assert (spreads[0].lowest, spreads[0].highest, spreads[0].spread) == (4, 9, 5)
    assert spreads[1].spread == 0


def test_markdown_shows_the_variance_table_for_repeat_runs() -> None:
    text = markdown.to_markdown(_repeated())
    assert "## Score variance across repetitions" in text
    assert "| horarios_directo | 3 | 7.0 | 4-9 | 5 |" in text


def test_markdown_omits_the_variance_table_for_a_single_run() -> None:
    assert "Score variance" not in markdown.to_markdown(_results())


def test_html_shows_the_variance_card_for_repeat_runs() -> None:
    page = html.to_html(_repeated(), metadata=METADATA)
    assert "Score variance across repetitions" in page
    assert "4–9" in page


def test_html_omits_the_variance_card_for_a_single_run() -> None:
    assert "Score variance" not in html.to_html(_results(), metadata=METADATA)
