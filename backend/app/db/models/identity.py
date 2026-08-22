"""Who the system knows: staff accounts, executives and their skills, and the
client references an identification is matched against.
"""

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.columns import string_enum
from app.domain.enums import (
    Category,
    ExecutiveStatus,
    UserRole,
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(string_enum(UserRole))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    executive_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("executives.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    executive: Mapped["Executive | None"] = relationship(back_populates="user")


class RefreshSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refresh_sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "client_references"

    display_name: Mapped[str] = mapped_column(String(120))
    identifier_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    masked_identifier: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Executive(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "executives"

    display_name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(120))
    window_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[ExecutiveStatus] = mapped_column(
        string_enum(ExecutiveStatus), default=ExecutiveStatus.DISPONIBLE, index=True
    )
    last_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    user: Mapped[User | None] = relationship(back_populates="executive", uselist=False)
    skills: Mapped[list["ExecutiveSkill"]] = relationship(
        back_populates="executive", cascade="all, delete-orphan"
    )


class ExecutiveSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "executive_skills"
    __table_args__ = (UniqueConstraint("executive_id", "category"),)

    executive_id: Mapped[UUID] = mapped_column(
        ForeignKey("executives.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[Category] = mapped_column(string_enum(Category), index=True)
    description: Mapped[str] = mapped_column(Text)
    experience_level: Mapped[int] = mapped_column(Integer, default=1)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    executive: Mapped[Executive] = relationship(back_populates="skills")
