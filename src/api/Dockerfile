FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# curl is used by the compose-level healthcheck (`python:3.12-slim` ships without it).
# procps ships pkill/pgrep, used by scripts/cron-dbt-run.sh to reap a stuck
# in-container `dbt build` from the host after the 14-minute timeout fires
# (TM-27 / PR #100). The unprivileged runtime user is created in the same
# layer so subsequent COPY --chown directives can reference it without a
# heavy recursive chown.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1001 --no-create-home --shell /usr/sbin/nologin app

RUN pip install --no-cache-dir uv==0.5.7

COPY pyproject.toml uv.lock ./
# dbt is needed at runtime so the host cron entry can shell into this
# container via `docker exec` and run `dbt run` without rebuilding.
# rag is needed because the weekly `rag-ingest` cron also runs inside this
# container via `docker exec` and pulls docling + llama-index + pinecone.
# UV_PROJECT_ENVIRONMENT=/usr/local makes the resulting console scripts
# (uvicorn, dbt, ...) resolve directly from $PATH at runtime; no `uv run`
# wrapping needed in production.
RUN uv sync --frozen --no-dev --group dbt --group rag --no-install-project

COPY --chown=app:app src ./src
COPY --chown=app:app contracts ./contracts
COPY --chown=app:app dbt ./dbt

ENV PYTHONPATH=/app/src

# dbt is invoked at runtime via `docker exec` from the host cron, which runs in
# WORKDIR /app (not the dbt project dir) and as the `app` user, which has no
# home (--no-create-home above). dbt's default profiles lookup at ~/.dbt then
# resolves to a non-existent /home/app/.dbt and fails. Point it at the project
# dir where profiles.yml is copied so every dbt invocation finds its profile.
ENV DBT_PROFILES_DIR=/app/dbt

USER app

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
