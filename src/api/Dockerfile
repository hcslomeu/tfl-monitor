FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# curl is used by the compose-level healthcheck (`python:3.12-slim` ships without it).
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.5.7

COPY pyproject.toml uv.lock ./
# dbt is needed at runtime so the host cron entry can shell into this
# container via `docker exec` and run `dbt run` without rebuilding.
RUN uv sync --frozen --no-dev --group dbt --no-install-project

COPY src ./src
COPY contracts ./contracts
COPY dbt ./dbt

ENV PYTHONPATH=/app/src

RUN useradd --system --uid 1001 --no-create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
