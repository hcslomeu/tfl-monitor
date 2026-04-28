"""DAG-level smoke tests.

Hermetic: Airflow's ``DagBag`` parses the DAG files with no external
services. Gated behind the ``airflow`` pytest marker so the default
``uv run task test`` run stays fast for contributors who don't need
Airflow installed.

Run explicitly with::

    uv run pytest -m airflow tests/airflow -v

or via the convenience target::

    make airflow-test
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.airflow

DAGS_DIR = Path(__file__).resolve().parents[2] / "airflow" / "dags"

DAG_FILES = sorted(p for p in DAGS_DIR.glob("*.py") if not p.name.startswith("_"))


@pytest.fixture(scope="module")
def dag_bag() -> object:
    """Load all DAGs once per test module."""
    from airflow.models.dagbag import DagBag

    return DagBag(dag_folder=str(DAGS_DIR), include_examples=False)


def test_dag_bag_no_import_errors(dag_bag: object) -> None:
    """Every DAG file under airflow/dags/ must parse without errors."""
    import_errors = dag_bag.import_errors  # type: ignore[attr-defined]
    assert import_errors == {}, f"Airflow DAG import errors: {import_errors}"


def test_at_least_one_dag_discovered(dag_bag: object) -> None:
    """Sanity guard: the DAG folder must not be empty."""
    dags = dag_bag.dags  # type: ignore[attr-defined]
    assert len(dags) >= 1, "expected at least one DAG to be discovered"


@pytest.mark.parametrize(
    "dag_file",
    DAG_FILES,
    ids=[p.stem for p in DAG_FILES],
)
def test_dag_contract(dag_bag: object, dag_file: Path) -> None:
    """Each DAG meets the contract documented in TM-A2-plan.md §6."""
    expected_dag_id = dag_file.stem
    dags = dag_bag.dags  # type: ignore[attr-defined]
    assert expected_dag_id in dags, (
        f"file {dag_file.name} did not register a DAG named '{expected_dag_id}'"
    )
    dag = dags[expected_dag_id]

    default_args = dag.default_args
    assert default_args.get("owner") == "tfl-monitor"
    assert default_args.get("retries", 0) >= 1
    assert isinstance(default_args.get("retry_delay"), timedelta)

    assert len(dag.tasks) >= 1, f"DAG {expected_dag_id} has no tasks"
    assert dag.catchup is False
    assert dag.max_active_runs == 1

    schedule = getattr(dag, "schedule_interval", None) or getattr(dag, "schedule", None)
    assert schedule, f"DAG {expected_dag_id} must declare a schedule"
    assert isinstance(schedule, str), (
        f"DAG {expected_dag_id} schedule must be a cron string, got {type(schedule)!r}"
    )
