# Backend del Sistema de Orquestacion Bancaria

Monolito modular FastAPI que implementa el flujo descrito en el documento del proyecto:
voz, privacidad, clasificacion, prioridad, identificacion demostrativa, respuesta inicial,
derivacion, ticket, trazabilidad y dashboards.

## Inicio local

Requisitos: Docker, Python 3.12 o superior y `uv`.

```bash
docker compose up -d postgres
uv sync
uv run alembic upgrade head
uv run python -m app.db.seed
uv run python -m app.knowledge.cli build-pdfs
uv run python -m app.knowledge.cli ingest
uv run uvicorn app.main:app --reload
```

La aplicacion carga `.env` por defecto. Si no existe, copie `.env.example` como `.env`; si ya
existe, agregue solamente las variables faltantes. No reemplace ni publique `OPENAI_API_KEY`.

- OpenAPI: `http://localhost:8000/docs`
- Salud: `http://localhost:8000/api/v1/health/ready`
- Frontend permitido por defecto: `http://localhost:3000`

Usuarios de demostracion:

- Ejecutivo: `maria.fernandez@demo.example` y `SEED_EXECUTIVE_PASSWORD`.
- Gerencia: `gerencia@demo.example` y `SEED_MANAGER_PASSWORD`.
- Identificador ficticio: `DEMO-1001`.

Cambie todas las credenciales de semilla y secretos fuera del entorno local.

## Flujo del kiosco

1. `POST /api/v1/kiosk/sessions` crea una sesion y devuelve `session_token`.
2. Enviar ese token como `X-Session-Token` en las siguientes operaciones.
3. `POST .../realtime-token` entrega una credencial efimera para WebRTC; nunca devuelve la
   clave normal del servidor.
4. El frontend envia la transcripcion final a `POST .../turns`.
5. Atiende `CLARIFY` o presenta el resumen y usa `POST .../confirmation`.
6. Si se recibe `IDENTIFY`, usa un identificador ficticio con `POST .../identification`.
7. La respuesta final incluye ticket, orientacion automatica o ejecutivo/ventanilla.

El audio y la transcripcion original no se persisten. Solo se guarda texto enmascarado.

La respuesta automatica inicial usa exclusivamente la base RAG. Si no existe evidencia con el
umbral configurado, si el documento esta vencido o si OpenAI no esta disponible, el caso se deriva
a un ejecutivo. El modelo Realtime tiene deshabilitada la creacion automatica de respuestas; el
cliente de voz debe reproducir solamente el `speech_text` autorizado por el backend.

## Base documental RAG

Los PDFs indexables se generan en `../doc/rag` y la auditoria de arquitectura en
`../doc/auditoria_backend_arquitectura.pdf`:

```bash
uv run python -m app.knowledge.cli build-pdfs
uv run python -m app.knowledge.cli ingest
uv run python -m app.knowledge.cli status
uv run python -m app.knowledge.cli evaluate
```

`build-pdfs` es reproducible y tambien actualiza `manifest.json`. `ingest` extrae texto por pagina,
fragmenta por secciones, genera embeddings en lotes y solo reindexa documentos cuyo hash cambio.
Las versiones anteriores quedan inactivas. La ingestion requiere `OPENAI_API_KEY` y haber aplicado
las migraciones. `evaluate` ejecuta 25 consultas de recuperacion, incluyendo politicas que impiden
respuesta automatica para casos sensibles, personalizados o ambiguos.

Configuracion principal:

- `EMBEDDING_MODEL=text-embedding-3-small` y `EMBEDDING_DIMENSIONS=1536`.
- `RAG_TOP_K=5`, `RAG_MIN_SCORE=0.45` y `RAG_MAX_CONTEXT_TOKENS=3000`.
- `RAG_CHUNK_TOKENS=600` y `RAG_CHUNK_OVERLAP=100`.
- `RAG_CORPUS_DIR=../doc/rag` al ejecutar desde `backend`.

Las consultas personalizadas y sensibles nunca se resuelven automaticamente mediante RAG. Las
trazas guardan la consulta ya enmascarada, los identificadores de los fragmentos y un hash de la
respuesta, no el prompt con datos originales.

## Supabase

El backend usa un solo esquema: PostgreSQL/pgvector local en desarrollo o PostgreSQL de Supabase
en despliegue. No realiza doble escritura. `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` no son una
cadena de conexion SQL y por si solas no conectan SQLAlchemy. Copie desde el panel de Supabase las
cadenas PostgreSQL y configure `DATABASE_URL` para ejecucion y `DATABASE_MIGRATION_URL` para
Alembic. Habilite SSL segun la configuracion del proyecto y ejecute:

```bash
uv run alembic upgrade head
uv run python -m app.db.seed
uv run python -m app.knowledge.cli ingest
```

No publique la service-role key ni la clave de OpenAI. Si `SUPABASE_URL` esta presente pero
`DATABASE_URL` sigue en localhost, el arranque registra una advertencia sin mostrar credenciales.

## Verificacion

```bash
uv run ruff check .
uv run pytest
```

Las pruebas normales usan dobles de OpenAI y no consumen la API real.
