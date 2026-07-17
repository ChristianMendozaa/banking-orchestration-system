import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_identifier, hash_password, mask_identifier
from app.db.models import DemoClient, Executive, ExecutiveSkill, User
from app.db.session import SessionFactory
from app.domain.enums import Category, ExecutiveStatus, UserRole

settings = get_settings()


def load_seed_data() -> dict[str, Any]:
    path = Path(settings.seed_data_path)
    if not path.is_file():
        raise RuntimeError(f"No existe el archivo de semilla: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("El archivo de semilla debe contener un objeto JSON")
    return data


async def seed(db: AsyncSession) -> None:
    data = load_seed_data()
    for item in data.get("executives", []):
        name = str(item["name"])
        title = str(item["title"])
        window = str(item["window"])
        email = str(item["email"]).lower()
        skills = {
            Category(category): int(level)
            for category, level in dict(item.get("skills", {})).items()
        }
        executive = await db.scalar(select(Executive).where(Executive.display_name == name))
        if not executive:
            executive = Executive(
                display_name=name,
                title=title,
                window_number=window,
                status=ExecutiveStatus.DISPONIBLE,
            )
            db.add(executive)
            await db.flush()
        user = await db.scalar(select(User).where(User.email == email))
        if not user:
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(
                        settings.seed_executive_password.get_secret_value()
                    ),
                    role=UserRole.EXECUTIVE,
                    executive_id=executive.id,
                )
            )
        for category, level in skills.items():
            skill = await db.scalar(
                select(ExecutiveSkill).where(
                    ExecutiveSkill.executive_id == executive.id,
                    ExecutiveSkill.category == category,
                )
            )
            if not skill:
                db.add(
                    ExecutiveSkill(
                        executive_id=executive.id,
                        category=category,
                        description=f"Especialista en {category.value.replace('_', ' ').lower()}",
                        experience_level=level,
                    )
                )

    manager_email = str(data["manager"]["email"]).lower()
    if not await db.scalar(select(User).where(User.email == manager_email)):
        db.add(
            User(
                email=manager_email,
                password_hash=hash_password(settings.seed_manager_password.get_secret_value()),
                role=UserRole.MANAGER,
            )
        )

    for client in data.get("clients", []):
        identifier = str(client["identifier"])
        name = str(client["name"])
        identifier_hash = hash_identifier(identifier, settings)
        if not await db.scalar(
            select(DemoClient).where(DemoClient.identifier_hash == identifier_hash)
        ):
            db.add(
                DemoClient(
                    display_name=name,
                    identifier_hash=identifier_hash,
                    masked_identifier=mask_identifier(identifier),
                )
            )

    await db.commit()


async def main() -> None:
    async with SessionFactory() as db:
        await seed(db)
    print("Datos de demostracion cargados.")


if __name__ == "__main__":
    asyncio.run(main())
