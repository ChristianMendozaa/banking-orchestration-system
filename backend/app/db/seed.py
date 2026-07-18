import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_identifier, hash_password, mask_identifier
from app.db.models import ClientReference, Executive, ExecutiveSkill, User
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
        skills = {}
        for category, raw_skill in dict(item.get("skills", {})).items():
            if isinstance(raw_skill, dict):
                level = int(raw_skill["level"])
                description = str(raw_skill["description"])
            else:
                level = int(raw_skill)
                description = f"Especialista en {category.replace('_', ' ').lower()}"
            skills[Category(category)] = (level, description)
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
        else:
            executive.title = title
            executive.window_number = window
        user = await db.scalar(select(User).where(User.executive_id == executive.id))
        if not user:
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
        else:
            user.email = email
            user.role = UserRole.EXECUTIVE
            user.executive_id = executive.id
            user.active = True
        for category, (level, description) in skills.items():
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
                        description=description,
                        experience_level=level,
                    )
                )
            else:
                if skill.description != description:
                    skill.description = description
                    skill.embedding = None
                skill.experience_level = level
        existing_skills = list(
            (
                await db.scalars(
                    select(ExecutiveSkill).where(ExecutiveSkill.executive_id == executive.id)
                )
            ).all()
        )
        for skill in existing_skills:
            if skill.category not in skills:
                await db.delete(skill)

    manager_email = str(data["manager"]["email"]).lower()
    manager = await db.scalar(select(User).where(User.role == UserRole.MANAGER).limit(1))
    if not manager:
        db.add(
            User(
                email=manager_email,
                password_hash=hash_password(settings.seed_manager_password.get_secret_value()),
                role=UserRole.MANAGER,
            )
        )
    else:
        manager.email = manager_email
        manager.active = True

    desired_reference_hashes: set[str] = set()
    for reference in data.get("client_references", []):
        identifier = str(reference["identifier"])
        name = str(reference["name"])
        identifier_hash = hash_identifier(identifier, settings)
        desired_reference_hashes.add(identifier_hash)
        stored = await db.scalar(
            select(ClientReference).where(ClientReference.identifier_hash == identifier_hash)
        )
        if not stored:
            db.add(
                ClientReference(
                    display_name=name,
                    identifier_hash=identifier_hash,
                    masked_identifier=mask_identifier(identifier),
                )
            )
        else:
            stored.display_name = name
            stored.masked_identifier = mask_identifier(identifier)
            stored.active = True
    references = list((await db.scalars(select(ClientReference))).all())
    for reference in references:
        if reference.identifier_hash not in desired_reference_hashes:
            reference.active = False

    await db.commit()


async def main() -> None:
    async with SessionFactory() as db:
        await seed(db)
    print("Datos operativos cargados.")


if __name__ == "__main__":
    asyncio.run(main())
