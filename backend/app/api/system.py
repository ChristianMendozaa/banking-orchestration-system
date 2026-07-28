from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.domain.schemas import PublicSystemConfig

router = APIRouter(prefix="/system", tags=["Configuracion publica"])


@router.get("/public-config", response_model=PublicSystemConfig)
async def public_config(settings: Settings = Depends(get_settings)) -> PublicSystemConfig:
    return PublicSystemConfig(
        app_name=settings.app_name,
        bank_name=settings.bank_name,
        branch_name=settings.branch_name,
        dashboard_refresh_ms=settings.dashboard_refresh_ms,
        conversation_retention_days=settings.conversation_retention_days,
    )
