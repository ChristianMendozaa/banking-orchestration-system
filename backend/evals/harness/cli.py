"""CLI entrypoint: `python -m harness [options]`.

Exits non-zero if any persona failed a check, so it works as a CI gate. Requires a live
backend (`EVAL_API_BASE_URL`, default http://localhost:8000) and `OPENAI_API_KEY` for
the Simulated Customer agent's LLM calls -- real API cost per run.
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence

from harness.evaluator import EvalResult
from harness.runner import run_all
from harness.scorecard import to_dict, to_markdown


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evalua la politica de orquestacion del kiosco de punta a punta."
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("EVAL_API_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument("--model", default=os.environ.get("EVAL_MODEL", "gpt-4o-mini"))
    parser.add_argument(
        "--max-clarifications",
        type=int,
        default=int(os.environ.get("EVAL_MAX_CLARIFICATIONS", "2")),
        help="Debe coincidir con MAX_CLARIFICATIONS del backend evaluado.",
    )
    parser.add_argument("--output", default=None, help="Ruta para el scorecard en markdown")
    parser.add_argument("--json-output", default=None, help="Ruta para el scorecard en JSON")
    return parser.parse_args(argv)


async def _run(argv: Sequence[str]) -> list[EvalResult]:
    args = _parse_args(argv)
    results = await run_all(
        base_url=args.base_url,
        model=args.model,
        max_clarifications=args.max_clarifications,
    )
    markdown = to_markdown(results)
    print(markdown)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(markdown)
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as handle:
            json.dump(to_dict(results), handle, ensure_ascii=False, indent=2)
    return results


def main() -> None:
    results = asyncio.run(_run(sys.argv[1:]))
    sys.exit(0 if all(result.passed for result in results) else 1)


if __name__ == "__main__":
    main()
