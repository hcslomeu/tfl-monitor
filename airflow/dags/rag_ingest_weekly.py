"""Weekly RAG ingestion: refresh the Pinecone strategy-doc index.

Re-runs ``python -m rag.ingest`` once a week on Monday at 03:00 UTC.
The pipeline is idempotent: HTTP 304 short-circuits unchanged PDFs and
chunk IDs are deterministic, so a re-run on a stable corpus only burns
a few cache lookups. Mondays/03:00 keeps it off-peak for both TfL's
static asset hosts and the OpenAI / Pinecone APIs.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator

DEFAULT_ARGS = {
    "owner": "tfl-monitor",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
}


with DAG(
    dag_id="rag_ingest_weekly",
    description="Weekly Docling -> OpenAI -> Pinecone refresh of TfL strategy docs.",
    default_args=DEFAULT_ARGS,
    schedule="0 3 * * 1",
    start_date=pendulum.datetime(2026, 4, 28, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["tfl-monitor", "rag"],
) as dag:
    rag_ingest = BashOperator(
        task_id="rag_ingest",
        bash_command="cd /opt/tfl-monitor && uv run python -m rag.ingest",
    )
