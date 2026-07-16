export type Category =
  | 'BLOQUEO_TARJETA'
  | 'REPORTE_FRAUDE'
  | 'CONSULTA_GENERAL'
  | 'SOLICITUD_CREDITO'
  | 'BANCA_DIGITAL'

export type Priority = 'CRITICO' | 'ALTO' | 'MEDIO' | 'BAJO'

export type Status = 'PENDIENTE' | 'EN_ATENCION' | 'CERRADO'

export interface Ticket {
  id: string
  number: string
  category: Category
  priority: Priority
  summary: string
  timeAssigned: string
  minutesElapsed: number
  executiveName: string
  executiveTitle: string
  windowNumber: string
  status: Status
  clientSessionId: string
  waitTimeMin: number
}

export interface TimelineEvent {
  id: string
  description: string
  time: string
}

export interface ManagerialCase {
  ticket: string
  category: Category
  priority: Priority
  executive: string
  status: Status
  attentionTime: string
}

export const tickets: Ticket[] = [
  {
    id: '2031',
    number: '2031',
    category: 'BLOQUEO_TARJETA',
    priority: 'ALTO',
    summary: 'Bloqueo de tarjeta de débito por extravío reportado esta mañana',
    timeAssigned: '09:15',
    minutesElapsed: 8,
    executiveName: 'Lic. María Fernández',
    executiveTitle: 'Tarjetas y Seguridad',
    windowNumber: 'Ventanilla 3',
    status: 'EN_ATENCION',
    clientSessionId: 'SES-****-7842',
    waitTimeMin: 6,
  },
  {
    id: '2028',
    number: '2028',
    category: 'REPORTE_FRAUDE',
    priority: 'CRITICO',
    summary: 'Movimiento no reconocido de Bs. 4500 en cuenta de ahorros',
    timeAssigned: '09:02',
    minutesElapsed: 21,
    executiveName: 'Lic. Carlos Mamani',
    executiveTitle: 'Prevención de Fraudes',
    windowNumber: 'Ventanilla 1',
    status: 'EN_ATENCION',
    clientSessionId: 'SES-****-3391',
    waitTimeMin: 4,
  },
  {
    id: '2025',
    number: '2025',
    category: 'CONSULTA_GENERAL',
    priority: 'BAJO',
    summary: 'Consulta sobre requisitos para apertura de cuenta empresarial',
    timeAssigned: '08:48',
    minutesElapsed: 35,
    executiveName: 'Lic. Carlos Mamani',
    executiveTitle: 'Atención al Cliente',
    windowNumber: 'Ventanilla 2',
    status: 'PENDIENTE',
    clientSessionId: 'SES-****-5510',
    waitTimeMin: 10,
  },
  {
    id: '2022',
    number: '2022',
    category: 'SOLICITUD_CREDITO',
    priority: 'MEDIO',
    summary: 'Solicitud de información sobre crédito hipotecario a 20 años',
    timeAssigned: '08:33',
    minutesElapsed: 50,
    executiveName: 'Lic. Carlos Mamani',
    executiveTitle: 'Créditos y Financiamiento',
    windowNumber: 'Ventanilla 4',
    status: 'PENDIENTE',
    clientSessionId: 'SES-****-9023',
    waitTimeMin: 8,
  },
  {
    id: '2019',
    number: '2019',
    category: 'BANCA_DIGITAL',
    priority: 'ALTO',
    summary: 'No puede acceder a banca en línea, contraseña bloqueada',
    timeAssigned: '08:20',
    minutesElapsed: 63,
    executiveName: 'Lic. Carlos Mamani',
    executiveTitle: 'Banca Digital',
    windowNumber: 'Ventanilla 5',
    status: 'CERRADO',
    clientSessionId: 'SES-****-6677',
    waitTimeMin: 5,
  },
]

export const timelineEvents: TimelineEvent[] = [
  { id: '1', description: 'Requerimiento capturado por voz', time: '09:14' },
  { id: '2', description: 'Datos sensibles enmascarados', time: '09:14' },
  { id: '3', description: 'Caso clasificado: BLOQUEO_TARJETA', time: '09:14' },
  { id: '4', description: 'Prioridad asignada: ALTA', time: '09:15' },
  { id: '5', description: 'Derivado a ejecutivo Lic. María Fernández', time: '09:15' },
]

export const kpiData = {
  totalToday: 47,
  inProgress: 8,
  avgWaitMin: 12,
  critical: 3,
}

export const categoryDistribution = [
  { name: 'Consulta General', value: 35, color: '#6B7280' },
  { name: 'Bloqueo Tarjeta', value: 25, color: '#F59E0B' },
  { name: 'Solicitud Crédito', value: 20, color: '#1168BD' },
  { name: 'Banca Digital', value: 12, color: '#8B5CF6' },
  { name: 'Reporte Fraude', value: 8, color: '#EF4444' },
]

export const hourlyData = [
  { hour: '08:00', casos: 5 },
  { hour: '09:00', casos: 8 },
  { hour: '10:00', casos: 12 },
  { hour: '11:00', casos: 15 },
  { hour: '12:00', casos: 7 },
  { hour: '13:00', casos: 10 },
  { hour: '14:00', casos: 9 },
  { hour: '15:00', casos: 6 },
]

export const managerialCases: ManagerialCase[] = [
  { ticket: '#2031', category: 'BLOQUEO_TARJETA', priority: 'ALTO', executive: 'M. Fernández', status: 'EN_ATENCION', attentionTime: '8 min' },
  { ticket: '#2028', category: 'REPORTE_FRAUDE', priority: 'CRITICO', executive: 'C. Mamani', status: 'EN_ATENCION', attentionTime: '21 min' },
  { ticket: '#2025', category: 'CONSULTA_GENERAL', priority: 'BAJO', executive: 'C. Mamani', status: 'PENDIENTE', attentionTime: '—' },
  { ticket: '#2022', category: 'SOLICITUD_CREDITO', priority: 'MEDIO', executive: 'C. Mamani', status: 'PENDIENTE', attentionTime: '—' },
  { ticket: '#2019', category: 'BANCA_DIGITAL', priority: 'ALTO', executive: 'P. Quispe', status: 'CERRADO', attentionTime: '14 min' },
  { ticket: '#2016', category: 'CONSULTA_GENERAL', priority: 'BAJO', executive: 'R. Torrez', status: 'CERRADO', attentionTime: '5 min' },
  { ticket: '#2013', category: 'SOLICITUD_CREDITO', priority: 'ALTO', executive: 'M. Fernández', status: 'CERRADO', attentionTime: '18 min' },
  { ticket: '#2010', category: 'BANCA_DIGITAL', priority: 'MEDIO', executive: 'P. Quispe', status: 'CERRADO', attentionTime: '9 min' },
  { ticket: '#2007', category: 'REPORTE_FRAUDE', priority: 'CRITICO', executive: 'C. Mamani', status: 'CERRADO', attentionTime: '32 min' },
  { ticket: '#2004', category: 'BLOQUEO_TARJETA', priority: 'MEDIO', executive: 'R. Torrez', status: 'CERRADO', attentionTime: '7 min' },
]
