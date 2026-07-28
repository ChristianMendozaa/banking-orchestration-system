"""Exporta el contrato OpenAPI canónico para consumidores tipados."""

import json
import sys
from copy import deepcopy
from pathlib import Path

from app.main import app

CANONICAL_OPENAPI_TITLE = "Sistema de Orquestacion Bancaria"


def canonical_openapi_schema() -> dict:
    """Devuelve un contrato estable aunque cambie la configuración del despliegue."""
    schema = deepcopy(app.openapi())
    schema["info"]["title"] = CANONICAL_OPENAPI_TITLE
    return schema


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python scripts/export_openapi.py <archivo-salida>")
    target = Path(sys.argv[1]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(canonical_openapi_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
