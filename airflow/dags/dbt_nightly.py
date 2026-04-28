"""Nightly dbt build for the analytics warehouse.

Runs ``dbt build`` (= ``run`` + ``test`` + ``seed`` + ``snapshot``)
against the ``dev`` profile, which targets the same Postgres instance
the streaming consumers write into. Scheduled at 01:00 UTC so the
previous day's late events have flushed into the raw tables before
the marts roll up.
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
    dag_id="dbt_nightly",
    description="Nightly dbt build over the tfl-monitor analytics warehouse.",
    default_args=DEFAULT_ARGS,
    schedule="0 1 * * *",
    start_date=pendulum.datetime(2026, 4, 28, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["tfl-monitor", "dbt"],
) as dag:
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            "cd /opt/tfl-monitor && "
            "uv run dbt build --project-dir dbt --profiles-dir dbt --target dev"
        ),
    )
