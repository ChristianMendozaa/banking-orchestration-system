# Auditoría integral de implementación

**Proyecto:** Sistema de Orquestación de Atención al Cliente Bancario

**Documento contrastado:** `TG1_ChristianMendoza.pdf`, 100 páginas

**Fecha de corte:** 17 de julio de 2026, zona `America/La_Paz`

**Alcance:** conversación por voz, privacidad, clasificación, prioridad, RAG,
derivación, tickets, trazabilidad, operación ejecutiva, gestión gerencial,
persistencia, configuración, pruebas y despliegue.

## Dictamen ejecutivo

El sistema implementa el recorrido descrito en el documento: escucha continua,
confirmación por voz, clasificación, aclaración, prioridad, verificación protegida
cuando corresponde, respuesta con evidencia o derivación humana, emisión de ticket,
asignación del ejecutivo compatible, ventanilla, espera estimada y trazabilidad.

Los 17 requerimientos funcionales cuentan con una ruta ejecutable. El frontend no
decide el resultado del negocio: las herramientas de voz delegan al orquestador y el
resultado persistido es la única fuente para la respuesta hablada y visual.

## Corrección del bloqueo conversacional

La sesión quedaba en `AWAITING_CONFIRMATION` antes de escuchar a la persona porque la
instrucción inicial de la aplicación se agregaba al historial como un mensaje de
usuario. El agente la enviaba a `analyze_requirement`, generaba un requerimiento y el
turno real posterior recibía `409`.

La instrucción de saludo y los mensajes controlados ahora se emiten mediante
`response.create`, sin crear un elemento de usuario y con herramientas deshabilitadas
para esa respuesta. Solo el audio pronunciado por la persona puede activar el
análisis. Además, un reintento de análisis mientras existe una confirmación pendiente
recupera el requerimiento activo de forma idempotente.

## Flujo operativo resultante

1. El kiosco crea una sesión corta y obtiene un secreto efímero para WebRTC.
2. La asistente saluda y escucha; la conversación admite interrupciones.
3. La transcripción se enmascara antes de clasificación y persistencia.
4. El orquestador clasifica, prioriza y solicita aclaración cuando falta contexto.
5. La asistente resume el requerimiento y pide confirmación por voz.
6. Una corrección vuelve a captura; una confirmación crea el caso.
7. Los casos personalizados o sensibles solicitan el código de cliente en un campo
   escrito protegido.
8. Una consulta general con evidencia vigente recibe respuesta RAG y ticket cerrado.
9. Los demás casos se asignan a un perfil compatible y generan ticket pendiente.
10. La pantalla y la voz informan número, ejecutivo, especialidad, ventanilla, espera
    estimada y canales de seguimiento.

## Asignación de ejecutivos

El registro declarativo se encuentra en
`backend/seed/operational_seed.json`. Incluye cuatro perfiles:

- Carlos Mamani: prevención de fraudes, Ventanilla 1.
- Maria Fernandez: tarjetas y seguridad, Ventanilla 3.
- Roberto Torrez: créditos y atención general, Ventanilla 4.
- Patricia Quispe: banca digital, Ventanilla 5.

La derivación exige una habilidad de la categoría y pondera 70% de afinidad
semántica, 20% de experiencia y 10% de disponibilidad. Los empates se resuelven por
menor carga activa y nombre. El catálogo reproducible está en
`doc/operacion/catalogo_perfiles_ejecutivos.pdf`.

La espera se calcula con ocho minutos por caso activo del ejecutivo, incluida la
asignación nueva. El valor se persiste en el ticket, se expone en las API de kiosco y
personal, se muestra en pantalla y se incluye en la locución final.

## Base documental

El corpus contiene ocho PDF declarados en `doc/rag/manifest.json`. Cada entrada
incluye versión, tipo de fuente, categorías, fecha de verificación, fecha de revisión
y SHA-256. La ingesta valida el hash antes de indexar.

Los documentos actualizados de banca digital, reclamos y manual de sucursal usan la
versión `2026.07.1`. El manual operativo está registrado como fuente `INTERNAL`. Tras
indexar una versión nueva, el bootstrap retira de la base y del almacenamiento las
versiones reemplazadas que administra el propio corpus.

Una respuesta automática requiere documento activo y vigente, categoría compatible,
similitud suficiente, respuesta sustentada y citas pertenecientes a los fragmentos
recuperados. Si falta cualquiera de estas condiciones, el caso pasa a atención
humana.

## Matriz de requerimientos funcionales

| ID | Estado | Evidencia y criterio |
|---|---|---|
| RF-01 | Cumple | `kiosk-provider.tsx` mantiene una sesión Realtime speech-to-speech con VAD, interrupciones y subtítulos en memoria. |
| RF-02 | Cumple | La confirmación se pronuncia por voz; la herramienta valida sí/no y el orquestador acepta o retorna a captura. |
| RF-03 | Cumple | `ClassificationAgent` produce una de las cinco categorías definidas en el dominio. |
| RF-04 | Cumple | El orquestador conserva contexto, emite `CLARIFY` y limita intentos de aclaración. |
| RF-05 | Cumple | `PIIMaskingService` elimina correo, tarjeta, cuenta, teléfono, identificador, monto y nombre antes del procesamiento de dominio y la persistencia. |
| RF-06 | Cumple | `PrioritizationAgent` considera categoría, urgencia, seguridad, angustia y atención preferente. |
| RF-07 | Cumple | Fraude o movimiento no reconocido resulta crítico; bloqueo por pérdida o robo resulta alto. |
| RF-08 | Cumple | `InitialAttentionAgent` usa RAG solo para nivel general; sin evidencia crea ticket humano. |
| RF-09 | Cumple | `DerivationAgent` exige habilidad compatible y pondera semántica, experiencia y carga. |
| RF-10 | Cumple | Sesión, requisito, caso, ticket y eventos quedan persistidos; los estados usan transiciones controladas. |
| RF-11 | Cumple | El panel ejecutivo muestra tickets asignados, resumen, prioridad, estado, espera y trazas. |
| RF-12 | Cumple | El panel gerencial obtiene métricas y casos filtrados desde la API. |
| RF-13 | Cumple | El resultado incluye ticket y canales publicados para seguimiento o reclamo. |
| RF-14 | Cumple | La atención preferente eleva prioridades bajas o medias sin desplazar casos críticos. |
| RF-15 | Cumple | Los niveles personalizado y sensible retornan `IDENTIFY` y abren el campo protegido. |
| RF-16 | Cumple | El código normalizado se verifica con HMAC; solo se conserva hash, máscara y resultado. |
| RF-17 | Cumple | Solo nivel general admite automatización; los demás niveles terminan en atención humana. |

## Matriz de requerimientos no funcionales

| ID | Estado | Evidencia y límite |
|---|---|---|
| RNF-01 | Cumple | Flujo guiado, confirmación por voz, subtítulos, estados visibles y recuperación ante errores. |
| RNF-02 | Controlado | Minimización, hash, masking y autorización están implementados; el proveedor de voz procesa el audio efímero antes del masking local. |
| RNF-03 | Cumple | Roles `EXECUTIVE` y `MANAGER`, JWT, sesión opaca y control de pertenencia de tickets. |
| RNF-04 | Cumple | Eventos para captura, masking, clasificación, prioridad, verificación, ruta, RAG y estados. |
| RNF-05 | Controlado | Healthchecks, dependencias condicionadas y recuperación del canal de voz; Compose cubre continuidad local. |
| RNF-06 | Pendiente de medición formal | Async I/O, timeout, batch, HNSW, top-k y paginación están presentes; falta fijar y medir un SLO concurrente. |
| RNF-07 | Cumple | API, dominio, servicios, repositorios, agentes y conocimiento mantienen límites explícitos. |
| RNF-08 | Cumple | Reglas, pesos, modelos, tiempos y fuentes se configuran; Alembic gestiona la evolución. |
| RNF-09 | Cumple | Tipado, lint, pruebas, manifiesto, semilla y documentación reproducible. |
| RNF-10 | Pendiente de certificación | Voz, subtítulos, etiquetas, campo escrito y atributos ARIA están presentes; falta auditoría WCAG 2.2 AA. |
| RNF-11 | Cumple | El alcance operativo está delimitado y no se ejecutan movimientos financieros desde el kiosco. |
| RNF-12 | Cumple | Métricas, trazas, matriz RF/RNF, evaluación RAG y reporte reproducible. |
| RNF-13 | Cumple | Código HMAC, valor parcialmente oculto y ausencia de audio o transcripción original en base. |
| RNF-14 | Cumple | La verificación escrita usa un control separado de la conversación y no solicita secretos financieros. |
| RNF-15 | Cumple | Cada ejecutivo ve sus tickets; gerencia ve agregados sin identificadores ni PII. |

## Persistencia y contratos

La migración `20260717_0004`:

- renombra el registro de clientes a `client_references`;
- renombra la referencia de identificación a `client_reference_id`;
- incorpora `tickets.estimated_wait_minutes`;
- normaliza el tipo de fuente interna a `INTERNAL`;
- conserva una ruta reversible para despliegues ya existentes.

`TicketResult`, `TicketListItem` y los endpoints de tickets exponen la espera
estimada. La traza `CASE_ROUTED` conserva puntajes de afinidad, experiencia,
disponibilidad, carga activa y tiempo calculado para auditoría.

## Seguridad y privacidad

- La API key del servidor no llega al navegador; Realtime recibe un secreto efímero.
- El código de cliente se escribe fuera del canal de voz.
- No se solicitan PIN, CVV, contraseñas, tokens ni números financieros completos.
- El identificador se normaliza y verifica con HMAC; su valor completo no se guarda.
- El audio y la transcripción original no se persisten.
- El frontend mantiene el access token en memoria y rota un refresh `HttpOnly`.
- Los roles limitan tickets, métricas y administración documental.
- Las cargas PDF validan firma, MIME, tamaño, páginas, texto y URL de fuente.

## Verificación automatizada

Resultado local del corte:

- `uv run ruff format --check .`: aprobado.
- `uv run ruff check .`: aprobado.
- `uv run pytest -q`: 28 pruebas aprobadas.
- `pnpm test`: 16 pruebas aprobadas.
- `pnpm lint`: aprobado.
- `pnpm typecheck`: aprobado.
- `pnpm build`: aprobado, 13 rutas.
- `python -m app.knowledge.cli evaluate`: 25 de 25 casos aprobados.
- `docker compose up -d --build`: migración, semilla, ingesta y healthchecks
  aprobados; ocho documentos activos y 42 fragmentos por sección.

Las pruebas cubren el bloqueo original de Realtime, idempotencia en confirmación,
flujo general, aclaración, corrección, prioridad, privacidad, verificación, asignación,
espera, RAG, retiro de versiones, roles, refresh, concurrencia y ciclo documental.

La prueba integral de fraude produjo prioridad `CRITICO`, verificación
`IDENTIFICADO`, ticket humano, Carlos Mamani, Ventanilla 1 y espera calculada. La
consulta sobre el horario de la línea gratuita produjo respuesta `GROUNDED`, cita a
la sección `Contact Center` y ticket automático cerrado.

## Riesgos operativos pendientes

1. **Proveedor de voz.** Definir consentimiento, retención, contrato de tratamiento y
   revisión legal para el audio procesado externamente.
2. **PII heurística.** Mantener una evaluación con corpus anonimizado y ampliar
   patrones o NER local cuando aparezcan nuevos formatos.
3. **Continuidad.** Para alta disponibilidad se requieren TLS de borde, réplicas,
   backup probado, monitoreo, alertas y recuperación ante desastre.
4. **Rate limiting.** En múltiples réplicas debe trasladarse del proceso a un gateway
   o almacén compartido.
5. **Rendimiento.** Definir SLO y ejecutar carga concurrente para clasificación, RAG,
   dashboards y cargas de PDF.
6. **Accesibilidad.** Completar WCAG 2.2 AA con teclado, lector de pantalla, contraste
   y pruebas con usuarios.
7. **Identidad del personal.** Integrar un IdP corporativo con MFA para la operación
   centralizada.

## Conclusión

El recorrido de atención ya no se bloquea por el saludo interno. Una solicitud real
puede avanzar desde la conversación y la confirmación por voz hasta el ticket, la
asignación del especialista, la ventanilla, la espera y el seguimiento. El catálogo
de perfiles, el registro declarativo, la traza de decisión y el corpus versionado
mantienen el comportamiento reproducible y auditable.
