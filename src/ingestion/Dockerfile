FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

RUN pip install --no-cache-dir uv==0.5.7

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY contracts ./contracts

ENV PYTHONPATH=/app/src

CMD ["uv", "run", "python", "-m", "ingestion.producers.line_status"]
