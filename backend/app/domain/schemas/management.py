"""Manager-facing schemas: metrics, the case register, and supervised overrides."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import (
    Category,
    ExecutiveStatus,
    Priority,
    ResolutionOutcome,
    TicketStatus,
)


class ManagerialCase(BaseModel):
    id: UUID
    ticket: str
    summary: str
    category: Category
    priority: Priority
    executive_id: UUID | None
    executive: str | None
    status: TicketStatus
    attention_time_min: int | None
    wait_time_min: int
    resolution_outcome: ResolutionOutcome | None
    created_at: datetime
    version: int


class MetricSlice(BaseModel):
    name: str
    value: int


class HourlyMetric(BaseModel):
    hour: str
    cases: int


class ManagementMetrics(BaseModel):
    total_cases: int
    active_cases: int
    pending_cases: int
    in_attention_cases: int
    closed_cases: int
    average_wait_minutes: float
    average_attention_minutes: float
    critical_pending: int
    unassigned_cases: int
    automatic_resolved: int
    human_routed: int
    automatic_resolution_rate: float
    wait_p50_minutes: float
    wait_p95_minutes: float
    oldest_pending_minutes: int
    by_category: list[MetricSlice]
    by_priority: list[MetricSlice]
    hourly: list[HourlyMetric]
    executives: list["ExecutiveWorkload"]


class ExecutiveWorkload(BaseModel):
    id: UUID
    name: str
    title: str
    status: ExecutiveStatus
    version: int
    pending: int
    in_attention: int
    closed: int


class ManagementCasesResponse(BaseModel):
    items: list[ManagerialCase]
    page: int
    page_size: int
    total: int


class ExecutiveStatusUpdate(BaseModel):
    status: ExecutiveStatus
    expected_version: int = Field(ge=1)

    @field_validator("status")
    @classmethod
    def restrict_managed_status(cls, value: ExecutiveStatus) -> ExecutiveStatus:
        if value == ExecutiveStatus.OCUPADO:
            raise ValueError("OCUPADO se administra mediante el estado de atención")
        return value


class ExecutiveStatusResult(BaseModel):
    id: UUID
    status: ExecutiveStatus
    version: int
    unassigned_tickets: int = 0


class TicketAssignmentUpdate(BaseModel):
    executive_id: UUID | None
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_assignment_reason(cls, value: str) -> str:
        return " ".join(value.split())


class TicketPriorityUpdate(BaseModel):
    priority: Priority
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_priority_reason(cls, value: str) -> str:
        return " ".join(value.split())


class ManagementTicketMutation(BaseModel):
    id: UUID
    number: str
    executive_id: UUID | None
    priority: Priority
    status: TicketStatus
    version: int


class PublicSystemConfig(BaseModel):
    app_name: str
    bank_name: str
    branch_name: str
    dashboard_refresh_ms: int
    conversation_retention_days: int
