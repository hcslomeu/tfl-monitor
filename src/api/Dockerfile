FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# curl is used by the compose-level healthcheck (`python:3.12-slim` ships without it).
# The unprivileged runtime user is created in the same layer so subsequent
# COPY --chown directives can reference it without a heavy recursive chown.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1001 --no-create-home --shell /usr/sbin/nologin app

RUN pip install --no-cache-dir uv==0.5.7

COPY pyproject.toml uv.lock ./
# dbt is needed at runtime so the host cron entry can shell into this
# container via `docker exec` and run `dbt run` without rebuilding.
# UV_PROJECT_ENVIRONMENT=/usr/local makes the resulting console scripts
# (uvicorn, dbt, ...) resolve directly from $PATH at runtime; no `uv run`
# wrapping needed in production.
RUN uv sync --frozen --no-dev --group dbt --no-install-project

COPY --chown=app:app src ./src
COPY --chown=app:app contracts ./contracts
COPY --chown=app:app dbt ./dbt

ENV PYTHONPATH=/app/src

USER app

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
