"""Staff login and session schemas."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.enums import UserRole
from app.domain.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserSummary(ORMModel):
    id: UUID
    email: EmailStr
    role: UserRole
    executive_id: UUID | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserSummary
