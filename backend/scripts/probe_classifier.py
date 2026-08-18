"""Measure how stable `OpenAIProvider.classify` is on the utterances that broke it.

The eval run of 2026-08-18 (`backend/evals/reports/runs/20260818T060910Z-db8608e`) has the
classifier returning GENERAL at 0.99 confidence for "Me robaron mi tarjeta de débito hace
unos minutos", while the same request phrased flatter came back SENSIBLE 0.99 four times out
of four. A full eval run is an expensive and noisy way to observe that: it exercises a
simulated customer, a judge and the whole graph to look at one label. This replays the
recorded openers straight through the classifier instead, several times each, and prints
what came back.

Two things it answers that the eval reports cannot:

- how *often* a given utterance flips, rather than what it happened to be in one run;
- what `security_incident` / `distress_detected` actually return, which nothing persists in
  the report and which `turn_nodes.requires_confirmation` now depends on.

Usage (from `backend/`, with OPENAI_API_KEY set):

    uv run python scripts/probe_classifier.py
    uv run python scripts/probe_classifier.py --repeat 5 --run <run_id>
"""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from app.core.config import get_settings
from app.domain.enums import Category
from app.services.agents import _LEVEL_ORDER, sensitivity_floor
from app.services.openai_provider import OpenAIProvider

RUNS_DIR = Path(__file__).parents[1] / "evals" / "reports" / "runs"


def _latest_run() -> Path:
    runs = sorted(path for path in RUNS_DIR.iterdir() if (path / "report.json").is_file())
    if not runs:
        raise SystemExit(f"no eval runs under {RUNS_DIR}")
    return runs[-1]


def _openers(run: Path) -> list[tuple[str, str]]:
    """(scenario, first customer utterance) for every scenario that produced one."""
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    openers = []
    for result in report["results"]:
        first = next(
            (
                step.get("customer")
                for step in result.get("transcript") or []
                if step.get("customer")
            ),
            None,
        )
        # Protocol scenarios record a turn_id or a header note rather than speech.
        if first and not first.startswith(("turn_id=", "sin ")):
            openers.append((result["scenario"], first))
    return openers


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3, help="calls per utterance")
    parser.add_argument("--run", default=None, help="run id under evals/reports/runs")
    parser.add_argument("--only", default=None, help="substring filter on the scenario name")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.openai_enabled:
        raise SystemExit("OPENAI_API_KEY is required to probe the classifier")
    run = RUNS_DIR / args.run if args.run else _latest_run()
    openers = [row for row in _openers(run) if not args.only or args.only in row[0]]
    provider = OpenAIProvider(settings)
    print(f"run={run.name} utterances={len(openers)} repeat={args.repeat}\n")

    unstable = 0
    for scenario, utterance in openers:
        decisions = await asyncio.gather(
            *(provider.classify(utterance) for _ in range(args.repeat))
        )
        levels = Counter(decision.consultation_level.value for decision in decisions)
        categories = Counter(decision.category.value for decision in decisions)
        flags = Counter()
        for decision in decisions:
            for name in ("urgency_detected", "security_incident", "distress_detected"):
                if getattr(decision, name):
                    flags[name] += 1
        floors = {sensitivity_floor(utterance, Category(category)) for category in categories}
        floor = max(
            (level for level in floors if level is not None),
            key=lambda level: _LEVEL_ORDER[level],
            default=None,
        )
        flip = len(levels) > 1
        unstable += flip
        marker = "FLIP" if flip else "    "
        print(f"{marker} {scenario:38s} {dict(levels)}")
        print(
            f"       categoria={dict(categories)} flags={dict(flags)} "
            f"piso={floor.value if floor else '-'}"
        )

    print(f"\n{unstable}/{len(openers)} utterances returned more than one level")


if __name__ == "__main__":
    asyncio.run(main())
