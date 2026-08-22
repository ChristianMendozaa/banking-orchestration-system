"""The ORM models, grouped into the four contexts they belong to.

| Module | Tables |
| --- | --- |
| `identity` | users, refresh sessions, client references, executives, skills |
| `kiosk` | kiosk sessions, conversation messages, requirements |
| `operations` | cases, identifications, tickets, trace and audit events |
| `knowledge` | documents, chunks, indexing jobs, RAG interactions |

Import order matters here: every module has to be imported for `Base.metadata` to be
complete, which is what `alembic/env.py` relies on when it does `from app.db import
models`. `operations` is the only module that imports its siblings, and it does so one
way -- the back-references pointing the other way are string annotations that SQLAlchemy
resolves through its declarative registry, so there is no cycle to break.
"""

from app.db.models.columns import string_enum
from app.db.models.identity import (
    ClientReference,
    Executive,
    ExecutiveSkill,
    RefreshSession,
    User,
)
from app.db.models.kiosk import ConversationMessage, KioskSession, Requirement
from app.db.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeJob,
    RAGInteraction,
)
from app.db.models.operations import (
    CaseRecord,
    Identification,
    OperationalAuditEvent,
    Ticket,
    TraceEvent,
)

__all__ = [
    "CaseRecord",
    "ClientReference",
    "ConversationMessage",
    "Executive",
    "ExecutiveSkill",
    "Identification",
    "KioskSession",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeJob",
    "OperationalAuditEvent",
    "RAGInteraction",
    "RefreshSession",
    "Requirement",
    "Ticket",
    "TraceEvent",
    "User",
    "string_enum",
]
