import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_identifier, hash_password, mask_identifier
from app.db.models import DemoClient, Executive, ExecutiveSkill, User
from app.db.session import SessionFactory
from app.domain.enums import Category, ExecutiveStatus, UserRole

settings = get_settings()


EXECUTIVES = (
    (
        "Maria Fernandez",
        "Tarjetas y Seguridad",
        "Ventanilla 3",
        "maria.fernandez@demo.example",
        ((Category.BLOQUEO_TARJETA, 5), (Category.REPORTE_FRAUDE, 4)),
    ),
    (
        "Carlos Mamani",
        "Prevencion de Fraudes",
        "Ventanilla 1",
        "carlos.mamani@demo.example",
        ((Category.REPORTE_FRAUDE, 5), (Category.CONSULTA_GENERAL, 3)),
    ),
    (
        "Patricia Quispe",
        "Banca Digital",
        "Ventanilla 5",
        "patricia.quispe@demo.example",
        ((Category.BANCA_DIGITAL, 5), (Category.BLOQUEO_TARJETA, 3)),
    ),
    (
        "Roberto Torrez",
        "Creditos y Atencion al Cliente",
        "Ventanilla 4",
        "roberto.torrez@demo.example",
        ((Category.SOLICITUD_CREDITO, 5), (Category.CONSULTA_GENERAL, 4)),
    ),
)


async def seed(db: AsyncSession) -> None:
    for name, title, window, email, skills in EXECUTIVES:
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
        for category, level in skills:
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

    if not await db.scalar(select(User).where(User.email == "gerencia@demo.example")):
        db.add(
            User(
                email="gerencia@demo.example",
                password_hash=hash_password(settings.seed_manager_password.get_secret_value()),
                role=UserRole.MANAGER,
            )
        )

    for identifier, name in (("DEMO-1001", "Cliente Demo Uno"), ("DEMO-1002", "Cliente Demo Dos")):
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
