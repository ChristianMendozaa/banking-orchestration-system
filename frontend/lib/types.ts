export type UserRole = "EXECUTIVE" | "MANAGER"
export type Category =
  | "BLOQUEO_TARJETA"
  | "REPORTE_FRAUDE"
  | "CONSULTA_GENERAL"
  | "SOLICITUD_CREDITO"
  | "BANCA_DIGITAL"
export type Priority = "CRITICO" | "ALTO" | "MEDIO" | "BAJO"
export type TicketStatus = "PENDIENTE" | "EN_ATENCION" | "CERRADO"
export type SessionStatus =
  | "CREATED"
  | "LISTENING"
  | "NEEDS_CLARIFICATION"
  | "AWAITING_CONFIRMATION"
  | "AWAITING_IDENTIFICATION"
  | "ORCHESTRATING"
  | "RESOLVED_AUTOMATIC"
  | "ASSIGNED"
  | "FAILED"
export type ConsultationLevel = "GENERAL" | "PERSONALIZADA" | "SENSIBLE"
export type KnowledgeSourceType = "OFFICIAL" | "REGULATORY" | "SIMULATED" | "HYBRID"
export type KnowledgeIndexStatus =
  | "PENDING"
  | "INDEXING"
  | "READY"
  | "FAILED"
  | "ARCHIVED"

export interface User {
  id: string
  email: string
  role: UserRole
  executive_id: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: "bearer"
  expires_in: number
  user: User
}

export interface PublicSystemConfig {
  app_name: string
  bank_name: string
  branch_name: string
  dashboard_refresh_ms: number
}

export interface KioskSession {
  session_id: string
  session_token: string
  status: SessionStatus
  expires_at: string
}

export interface TurnAnalysis {
  requirement_id: string
  status: SessionStatus
  summary: string
  category: Category
  priority: Priority
  consultation_level: ConsultationLevel
  confidence: number
  clarification_question: string | null
  pii_types: string[]
  next_action: "CLARIFY" | "CONFIRM"
  speech_text: string
}

export interface KnowledgeCitation {
  document_id: string
  chunk_id: string
  title: string
  section: string | null
  page: number
  source_url: string | null
  score: number
}

export interface FlowResult {
  session_id: string
  status: SessionStatus
  next_action: "CAPTURE" | "IDENTIFY" | "COMPLETE"
  identification_status: "ANONIMO" | "PENDIENTE" | "IDENTIFICADO" | "FALLIDO" | null
  resolution_type: "AUTOMATIC" | "HUMAN" | null
  ticket: { id: string; number: number; status: TicketStatus } | null
  executive: {
    id: string
    name: string
    title: string
    window_number: string
  } | null
  response: string | null
  speech_text: string
  tracking_information: string | null
  grounding_status: "NOT_APPLICABLE" | "GROUNDED" | "NO_EVIDENCE"
  citations: KnowledgeCitation[]
}

export interface TicketListItem {
  id: string
  number: string
  category: Category
  priority: Priority
  summary: string
  time_assigned: string | null
  minutes_elapsed: number
  executive_name: string | null
  executive_title: string | null
  window_number: string | null
  status: TicketStatus
  client_session_id: string
  wait_time_min: number
  identification_status: string
  preferential_attention: boolean
  version: number
}

export interface TicketPage {
  items: TicketListItem[]
  page: number
  page_size: number
  total: number
}

export interface TraceEvent {
  id: string
  event_type: string
  description: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface TicketDetail extends TicketListItem {
  consultation_level: ConsultationLevel
  events: TraceEvent[]
}

export interface MetricSlice {
  name: string
  value: number
}

export interface ManagementMetrics {
  total_cases: number
  active_cases: number
  average_wait_minutes: number
  critical_pending: number
  by_category: MetricSlice[]
  by_priority: MetricSlice[]
  hourly: { hour: string; cases: number }[]
}

export interface ManagerialCase {
  ticket: string
  category: Category
  priority: Priority
  executive: string | null
  status: TicketStatus
  attention_time_min: number | null
  created_at: string
}

export interface ManagementCasesPage {
  items: ManagerialCase[]
  page: number
  page_size: number
  total: number
}

export interface KnowledgeDocument {
  id: string
  slug: string
  title: string
  version: string
  source_type: KnowledgeSourceType
  categories: Category[]
  source_urls: string[]
  verified_at: string
  review_after: string | null
  file_name: string
  mime_type: string
  byte_size: number
  page_count: number
  content_sha256: string
  index_status: KnowledgeIndexStatus
  indexed_at: string | null
  index_error: string | null
  active: boolean
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface KnowledgeDocumentPage {
  items: KnowledgeDocument[]
  page: number
  page_size: number
  total: number
}

export interface KnowledgeOperation {
  document: KnowledgeDocument
  indexed_chunks: number
}
