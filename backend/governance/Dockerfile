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

WORKDIR /workspace/governance
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev \
    && chown -R app:app /home/app

COPY --chown=app:app . ./

USER app
ENTRYPOINT ["/workspace/governance/.venv/bin/python", "-m", "crew"]
