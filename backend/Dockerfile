FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy
ENV HOME=/home/app
ENV UV_CACHE_DIR=/home/app/.cache/uv

RUN addgroup --system --gid 1001 app \
    && adduser --system --uid 1001 --ingroup app --home /home/app app \
    && mkdir -p /home/app/.cache/uv \
    && chown -R app:app /home/app

WORKDIR /workspace/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev \
    && chown -R app:app /home/app

COPY --chown=app:app backend ./
COPY --chown=app:app doc/rag /workspace/doc/rag
RUN mkdir -p /workspace/data/knowledge \
    && chown -R app:app /workspace/data

USER app
EXPOSE 8000
CMD ["/workspace/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
