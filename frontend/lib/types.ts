import type { components } from "@/lib/generated-api"

type Schemas = components["schemas"]

export type UserRole = Schemas["UserRole"]
export type Category = Schemas["Category"]
export type Priority = Schemas["Priority"]
export type TicketStatus = Schemas["TicketStatus"]
export type ExecutiveStatus = Schemas["ExecutiveStatus"]
export type ResolutionOutcome = Schemas["ResolutionOutcome"]
export type SessionStatus = Schemas["SessionStatus"]
export type ConsultationLevel = Schemas["ConsultationLevel"]
export type KnowledgeSourceType = Schemas["KnowledgeSourceType"]
export type KnowledgeIndexStatus = Schemas["KnowledgeIndexStatus"]

export type User = Schemas["UserSummary"]
export type TokenResponse = Schemas["TokenResponse"]
export type PublicSystemConfig = Schemas["PublicSystemConfig"]
export type KioskSession = Schemas["SessionCreatedResponse"]
// What the voice channel receives instead of a sentence to read out: the facts the backend
// decided, one line of guidance, and the strings that must survive word for word. See
// SpeechPlan in backend/app/domain/schemas.py.
export type SpeechPlan = Schemas["SpeechPlan"]
export type KnowledgeCitation = Schemas["KnowledgeCitation"]
export type FlowResult = Omit<Schemas["FlowResult"], "citations"> & {
  citations: Schemas["KnowledgeCitation"][]
}
// A confident GENERAL request now resolves on the same turn (see
// turn_nodes.requires_confirmation on the backend): next_action can be "COMPLETE" with the
// answer embedded in `result`. Reshaped the same way as the top-level FlowResult above so
// `analysis.result` and a `/confirmation` FlowResult are interchangeable everywhere in the
// frontend instead of `result.citations` being separately optional here. A COMPLETE whose
// resolution_type is AUTOMATIC does not end the session -- see isTerminalFlowResult.
export type TurnAnalysis = Omit<Schemas["TurnAnalysisResponse"], "result"> & {
  result?: FlowResult | null
}
export type KioskSessionStatus = Omit<
  Schemas["SessionStatusResponse"],
  "analysis" | "result"
> & {
  analysis?: TurnAnalysis | null
  result?: FlowResult | null
}
export type TicketListItem = Schemas["TicketListItem"]
export type TicketPage = Schemas["TicketPage"]
export type TraceEvent = Schemas["TraceEventOut"]
export type TicketDetail = Schemas["TicketDetail"]
export type MetricSlice = Schemas["MetricSlice"]
export type ManagementMetrics = Schemas["ManagementMetrics"]
export type ExecutiveWorkload = Schemas["ExecutiveWorkload"]
export type ManagerialCase = Schemas["ManagerialCase"]
export type ManagementCasesPage = Schemas["ManagementCasesResponse"]
export type KnowledgeDocument = Schemas["KnowledgeDocumentSummary"]
export type KnowledgeDocumentPage = Schemas["KnowledgeDocumentPage"]
export type KnowledgeJob = Schemas["KnowledgeJobSummary"]
export type KnowledgeJobResponse = Schemas["KnowledgeJobResponse"]
