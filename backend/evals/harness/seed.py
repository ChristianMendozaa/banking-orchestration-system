"""Reads the operational seed the evaluated backend was seeded from.

Only for assertions the harness cannot make from API responses alone: which categories an
executive actually holds a skill for, and which identity-card numbers exist in the client
reference registry. The file is the same one `SEED_DATA_PATH` points the backend at
(`backend/seed/operational_seed.json`), so the harness and the system under test agree on
the fixture by construction rather than by a copied constant.

A missing file is not fatal: the harness may legitimately run against a remote backend
whose seed is not on this machine, in which case the checks that need it report as
not-applicable instead of failing.
"""

import json
from functools import lru_cache
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[2] / "seed" / "operational_seed.json"


@lru_cache(maxsize=1)
def load_seed() -> dict:
    try:
        with open(SEED_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def skill_categories_for_executive(display_name: str) -> set[str] | None:
    """Categories `display_name` holds a skill for, or None if the seed is unavailable or
    does not know that executive."""
    executives = load_seed().get("executives")
    if not executives:
        return None
    for executive in executives:
        if executive.get("name") == display_name:
            return set(executive.get("skills", {}))
    return None


@lru_cache(maxsize=1)
def known_identifiers() -> frozenset[str]:
    """Identity-card numbers the backend will resolve to `IDENTIFICADO`."""
    return frozenset(
        reference["identifier"]
        for reference in load_seed().get("client_references", [])
        if reference.get("identifier")
    )
