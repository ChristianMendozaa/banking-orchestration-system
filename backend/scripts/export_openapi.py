"""Export the canonical OpenAPI contract for typed consumers."""

import json
import sys
from copy import deepcopy
from pathlib import Path

from app.main import app

CANONICAL_OPENAPI_TITLE = "Sistema de Orquestacion Bancaria"


def canonical_openapi_schema() -> dict:
    """Return a stable contract even if the deployment configuration changes."""
    schema = deepcopy(app.openapi())
    schema["info"]["title"] = CANONICAL_OPENAPI_TITLE
    return schema


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/export_openapi.py <output-file>")
    target = Path(sys.argv[1]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(canonical_openapi_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
