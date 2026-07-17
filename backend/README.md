# Backend FastAPI

Monolito modular que implementa el flujo de orquestación bancaria del prototipo:
privacidad, clasificación, desambiguación, prioridad, identificación ficticia,
respuesta RAG, derivación por habilidades, tickets, trazas, operación ejecutiva,
métricas gerenciales y gestión documental.

Para ejecutar el sistema completo consulte [`../README.md`](../README.md).

## Inicio local

Requisitos: Python 3.12 o superior, `uv` y PostgreSQL con la extensión `vector`.

```bash
uv sync
uv run alembic upgrade head
uv run python -m app.db.seed
uv run python -m app.knowledge.cli ingest
uv run uvicorn app.main:app --reload
```

La aplicación exige `APP_NAME`, `BANK_NAME`, `BRANCH_NAME`, `CORS_ORIGINS`,
`DATABASE_URL`, `JWT_SECRET`, `IDENTIFIER_PEPPER` y las contraseñas de semilla desde
`.env`; no existen datos de despliegue ni credenciales de respaldo en código. Copie
`.env.example` solo si `.env` aún no existe y reemplace todos los valores marcados.
No publique `OPENAI_API_KEY`.

- OpenAPI: `http://localhost:8000/docs`
- Salud: `http://localhost:8000/api/v1/health/ready`
- Configuración pública: `http://localhost:8000/api/v1/system/public-config`

## Kiosco y agentes

1. `POST /api/v1/kiosk/sessions` crea una sesión corta con token opaco.
2. Las siguientes llamadas usan `X-Session-Token`.
3. `POST .../realtime-token` crea un secreto efímero para WebRTC. La API key normal
   nunca sale del backend.
4. `POST .../turns` enmascara PII, clasifica y prioriza. El `turn_id` hace la operación
   idempotente.
5. El flujo responde `CLARIFY` o `CONFIRM`.
6. `POST .../confirmation` permite corrección o crea el caso.
7. Los niveles `PERSONALIZADA` y `SENSIBLE` solicitan identificación ficticia.
8. Las consultas `GENERAL` intentan RAG; cualquier falta de evidencia deriva a una
   persona.

Los agentes tienen responsabilidades separadas:

- `ClassificationAgent`: categoría, nivel, ambigüedad y señales de riesgo.
- `PrioritizationAgent`: prioridad determinista y atención preferente.
- `InitialAttentionAgent`: respuesta solo para nivel general, con evidencia RAG.
- `DerivationAgent`: habilidad exacta, similitud semántica, experiencia y carga.

El audio y la transcripción original no se persisten. La base guarda el texto
enmascarado. Realtime solo transcribe (`create_response=false`); el texto hablado al
cliente proviene del backend.

## Base de conocimiento

El bootstrap consume exclusivamente `../doc/rag/manifest.json`; no genera documentos
en tiempo de ejecución.

```bash
uv run python -m app.knowledge.cli ingest
uv run python -m app.knowledge.cli status
uv run python -m app.knowledge.cli evaluate
```

- `ingest`: valida manifiesto/hash, extrae texto, fragmenta y genera embeddings.
- `status`: informa documentos activos y fragmentos.
- `evaluate`: prueba recuperación y también clasifica los casos donde la política
  prohíbe respuesta automática.

La API gerencial bajo `/api/v1/management/knowledge/documents` permite listar,
cargar, editar, versionar, descargar, reindexar y archivar. Valida firma PDF, MIME,
tamaño, páginas, texto extraíble, categorías y URL HTTP(S). Los archivos se almacenan
con claves UUID; el nombre original es solo metadato.

Una respuesta automática requiere:

- consulta ya enmascarada;
- documento activo y no vencido;
- categoría compatible y similitud sobre el umbral;
- respuesta estructurada limitada a la evidencia recuperada;
- al menos una cita válida a un fragmento recuperado.

Ante cualquier incumplimiento se crea un ticket humano.

## Persistencia y migraciones

Las migraciones son explícitas y congeladas:

- `20260716_0001`: esquema operacional;
- `20260716_0002`: pgvector, documentos, fragmentos e interacciones RAG;
- `20260716_0003`: expiración, prioridad propuesta y ciclo documental.

No se usa `Base.metadata.create_all()` en migraciones. Los tests sí crean un esquema
SQLite efímero de forma aislada.

## Autorización

- JWT de acceso corto en memoria del frontend.
- Refresh opaco, rotado y almacenado como hash; cookie `HttpOnly`, `SameSite=Lax` y
  `Secure` en producción.
- Roles `EXECUTIVE` y `MANAGER`.
- Un ejecutivo solo consulta sus tickets; gerencia accede a métricas y conocimiento.
- Los estados de ticket usan versión optimista y transiciones cerradas.

## Verificación

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv run --with pip-audit pip-audit
```

Las pruebas no consumen OpenAI y cubren flujo general, aclaración, corrección,
identificación, prioridad, privacidad, RAG, caducidad, roles, refresh, concurrencia y
ciclo documental.

Para regenerar el PDF de auditoría desde su única fuente Markdown:

```bash
uv run python scripts/render_audit_pdf.py
```
