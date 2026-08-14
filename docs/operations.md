# Operación y recuperación

## Preparación de despliegue

1. Configure TLS en el proxy y orígenes CORS exactos.
2. Guarde credenciales, llaves de identificación, `METRICS_TOKEN` y claves de proveedores
   en un gestor de secretos.
3. Use PostgreSQL y almacenamiento documental con copias de seguridad independientes.
4. Mantenga Redis y ClamAV accesibles solo desde la red interna.
5. Ejecute `alembic upgrade head` antes de iniciar API, worker y MCP.
6. Valide `/api/v1/health/ready` y el `/healthz` del MCP, luego las dos superficies web.

En producción la configuración falla al iniciar si faltan OpenAI, Redis, ClamAV, una
llave exclusiva para cifrado de identificadores o el token de métricas.

## Servicios y observabilidad

- La API publica liveness y readiness bajo `/api/v1/health`.
- El proceso MCP publica `/healthz`; su endpoint `/mcp` exige un JWT vigente de ejecutivo
  o gerencia y no debe exponerse fuera de la red prevista para clientes MCP autorizados.
- Prometheus puede consultar `/internal/metrics` con
  `Authorization: Bearer <METRICS_TOKEN>`.
- Los logs son JSON, incluyen `trace_id`, ruta normalizada, estado y duración, y no
  registran texto de clientes ni identificadores.
- El worker `app.knowledge.worker` reclama trabajos con bloqueo, recupera trabajos
  interrumpidos y conserva el documento activo anterior cuando una reindexación falla.

Alertas iniciales recomendadas:

- tasa de respuestas 5xx mayor a 2 % durante 5 minutos;
- p95 HTTP superior a 2 segundos durante 10 minutos;
- rechazos por límite con crecimiento anómalo;
- readiness fallida por 2 minutos;
- health check del proceso MCP fallido por 2 minutos;
- trabajos documentales fallidos o en ejecución por más de 15 minutos;
- casos críticos o sin asignar por encima del umbral operativo;
- antigüedad del pendiente más antiguo por encima del SLA definido.

## Copias y restauración

Realice copias consistentes de PostgreSQL y del volumen `knowledge_data`. El archivo
documental y sus metadatos deben restaurarse al mismo punto lógico. Pruebe la
restauración en un entorno aislado al menos trimestralmente:

1. restaure base y volumen;
2. ejecute `alembic current` y verifique la revisión esperada;
3. ejecute `python -m app.knowledge.cli status`;
4. pruebe login, creación de sesión, asignación y descarga documental;
5. compare conteos y hashes documentales.

## Migración y reversión

Antes de migrar, tome una copia y revise el SQL de la nueva revisión. Si la aplicación
falla después de desplegar, revierta primero la versión de aplicación. Solo ejecute un
`alembic downgrade` cuando la revisión documente una reversión segura: una migración que
purga información no puede reconstruirla.

La revisión `20260813_0009` retira definitivamente la tabla histórica de propuestas
documentales. Su downgrade puede recrear la estructura, pero no los registros eliminados;
exporte esos datos antes de actualizar si existe una obligación de retención.

## Evaluación de política

El arnés AutoGen en `backend/evals` llama a la API REST del kiosco; no utiliza MCP. Sus
pruebas unitarias son locales y deterministas, pero la evaluación de punta a punta usa
OpenAI tanto para el cliente simulado como para el backend. No existe workflow de CI
para esta ejecución: se lanza manualmente desde una máquina local con un backend
`docker compose` en ejecución (ver `backend/evals/README.md`), y no debe automatizarse
en cada push o pull request por su costo real de OpenAI.

## Privacidad y retención

El audio y la transcripción original no se almacenan. Los mensajes completados se
enmascaran nuevamente en el backend y se purgan al cumplir
`CONVERSATION_RETENTION_DAYS`. Al cerrar un ticket se elimina el CI cifrado recuperable;
permanecen su hash, valor enmascarado y eventos de auditoría.

Verifique diariamente la ejecución del proceso de retención y documente las excepciones.
