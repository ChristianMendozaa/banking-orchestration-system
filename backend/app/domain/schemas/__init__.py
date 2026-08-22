"""API and AI schemas, grouped by the surface that exchanges them.

| Module | Surface |
| --- | --- |
| `common` | `ORMModel`, the base for schemas read straight off ORM rows |
| `auth` | staff login and session |
| `kiosk` | the kiosk flow, including `SpeechPlan` |
| `ai` | structured model output and grounding citations |
| `staff` | the executive ticket queue and its transitions |
| `management` | manager metrics, case register, supervised overrides |
| `knowledge` | corpus documents, versions and indexing jobs |

Every name stays importable from `app.domain.schemas`, so the twenty-one modules that
import from here are unchanged.
"""

from app.domain.schemas.ai import (
    ClassificationDecision,
    GroundedAnswerDecision,
    GroundedResponse,
    KnowledgeCitation,
)
from app.domain.schemas.auth import LoginRequest, TokenResponse, UserSummary
from app.domain.schemas.common import ORMModel
from app.domain.schemas.kiosk import (
    ConfirmationRequest,
    ConversationMessageInput,
    ConversationSyncRequest,
    ConversationSyncResponse,
    ExecutiveAssignment,
    FlowResult,
    IdentificationRequest,
    RealtimeTokenResponse,
    SessionCreatedResponse,
    SessionCreateRequest,
    SessionStatusResponse,
    SpeechPlan,
    TicketResult,
    TurnAnalysisResponse,
    TurnRequest,
)
from app.domain.schemas.knowledge import (
    KnowledgeDocumentPage,
    KnowledgeDocumentSummary,
    KnowledgeDocumentUpdate,
    KnowledgeJobResponse,
    KnowledgeJobSummary,
)
from app.domain.schemas.management import (
    ExecutiveStatusResult,
    ExecutiveStatusUpdate,
    ExecutiveWorkload,
    HourlyMetric,
    ManagementCasesResponse,
    ManagementMetrics,
    ManagementTicketMutation,
    ManagerialCase,
    MetricSlice,
    PublicSystemConfig,
    TicketAssignmentUpdate,
    TicketPriorityUpdate,
)
from app.domain.schemas.staff import (
    ConversationMessageOut,
    IdentifierRevealResponse,
    ProtectedIdentity,
    TicketDetail,
    TicketListItem,
    TicketPage,
    TicketStatusUpdate,
    TraceEventOut,
)

__all__ = [
    "ClassificationDecision",
    "ConfirmationRequest",
    "ConversationMessageInput",
    "ConversationMessageOut",
    "ConversationSyncRequest",
    "ConversationSyncResponse",
    "ExecutiveAssignment",
    "ExecutiveStatusResult",
    "ExecutiveStatusUpdate",
    "ExecutiveWorkload",
    "FlowResult",
    "GroundedAnswerDecision",
    "GroundedResponse",
    "HourlyMetric",
    "IdentificationRequest",
    "IdentifierRevealResponse",
    "KnowledgeCitation",
    "KnowledgeDocumentPage",
    "KnowledgeDocumentSummary",
    "KnowledgeDocumentUpdate",
    "KnowledgeJobResponse",
    "KnowledgeJobSummary",
    "LoginRequest",
    "ManagementCasesResponse",
    "ManagementMetrics",
    "ManagementTicketMutation",
    "ManagerialCase",
    "MetricSlice",
    "ORMModel",
    "ProtectedIdentity",
    "PublicSystemConfig",
    "RealtimeTokenResponse",
    "SessionCreateRequest",
    "SessionCreatedResponse",
    "SessionStatusResponse",
    "SpeechPlan",
    "TicketAssignmentUpdate",
    "TicketDetail",
    "TicketListItem",
    "TicketPage",
    "TicketPriorityUpdate",
    "TicketResult",
    "TicketStatusUpdate",
    "TokenResponse",
    "TraceEventOut",
    "TurnAnalysisResponse",
    "TurnRequest",
    "UserSummary",
]
