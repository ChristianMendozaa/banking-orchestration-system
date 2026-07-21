import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.security import hash_identifier
from app.db.models import ClientReference
from app.domain.schemas import IdentificationRequest
from tests.conftest import TestSession, settings_for_tests


@pytest.mark.parametrize(
    ("raw_identifier", "expected"),
    [
        ("6735666", "6735666"),
        ("  6735666-sc  ", "6735666-SC"),
        ("7842193-LP", "7842193-LP"),
    ],
)
def test_ci_is_validated_and_normalized(raw_identifier: str, expected: str) -> None:
    assert IdentificationRequest(identifier=raw_identifier).identifier == expected


@pytest.mark.parametrize(
    "invalid_identifier",
    [
        "CLI-1001",
        "123",
        "6735666-",
        "6735666-SCZQ",
        "67A5666",
    ],
)
def test_invalid_ci_formats_are_rejected(invalid_identifier: str) -> None:
    with pytest.raises(ValidationError):
        IdentificationRequest(identifier=invalid_identifier)


@pytest.mark.parametrize("ci", ["6735666", "7842193"])
async def test_seeded_client_cis_are_active(ci: str) -> None:
    async with TestSession() as db:
        reference = await db.scalar(
            select(ClientReference).where(
                ClientReference.identifier_hash == hash_identifier(ci, settings_for_tests),
                ClientReference.active.is_(True),
            )
        )

    assert reference is not None
