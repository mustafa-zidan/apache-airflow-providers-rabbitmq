"""Trigger every rmq_* DAG, wait for the runs, and check them against the walkthrough.

Run through `kind.sh verify`. Exits non-zero if any DAG doesn't end as expected.
"""

import subprocess
import sys
import time

from airflow.models import DagRun, TaskInstance
from airflow.utils.session import create_session

MANUAL_DAGS = [
    "rmq_01_publish_and_sense",
    "rmq_02_properties_and_json",
    "rmq_03_batch",
    "rmq_04_delivery_checks",
    "rmq_05_sensor_modes",
    "rmq_06_deferrable_trigger",
    "rmq_07_asset_producer",
    "rmq_08_tls",
    "rmq_99_expected_failures",
]
ASSET_CONSUMER = "rmq_07_asset_consumer"
TIMEOUT = 600


def airflow(*args: str) -> None:
    subprocess.run(["airflow", *args], check=True, capture_output=True)


def consumer_runs() -> int:
    with create_session() as session:
        return session.query(DagRun).filter_by(dag_id=ASSET_CONSUMER).count()


def latest_run(dag_id: str) -> tuple[str, dict[str, str]]:
    with create_session() as session:
        run = (
            session.query(DagRun)
            .filter_by(dag_id=dag_id)
            .order_by(DagRun.id.desc())
            .first()
        )
        tis = session.query(TaskInstance).filter_by(dag_id=dag_id, run_id=run.run_id)
        return run.state, {ti.task_id: ti.state for ti in tis}


def problems(dag_id: str, state: str, tasks: dict[str, str]) -> list[str]:
    """What differs from the expected outcome, empty when the run is as expected."""
    if dag_id != "rmq_99_expected_failures":
        if state == "success":
            return []
        return [f"{t}={s}" for t, s in sorted(tasks.items()) if s != "success"]
    # Every fail_* task fails; the publish_* helpers succeed.
    return [
        f"{t}={s}"
        for t, s in sorted(tasks.items())
        if s != ("failed" if t.startswith("fail_") else "success")
    ]


def main() -> int:
    for dag_id in [*MANUAL_DAGS, ASSET_CONSUMER]:
        airflow("dags", "unpause", dag_id)
    # Give the triggerer time to start the asset watcher once the consumer is unpaused.
    time.sleep(15)
    runs_before = consumer_runs()
    for dag_id in MANUAL_DAGS:
        airflow("dags", "trigger", dag_id)
    print(f"Triggered {len(MANUAL_DAGS)} DAGs, waiting up to {TIMEOUT}s...")

    deadline = time.monotonic() + TIMEOUT
    results: dict[str, tuple[str, dict[str, str]]] = {}
    while time.monotonic() < deadline:
        results = {dag_id: latest_run(dag_id) for dag_id in MANUAL_DAGS}
        if all(state in ("success", "failed") for state, _ in results.values()):
            break
        time.sleep(10)

    failed = False
    for dag_id, (state, tasks) in results.items():
        issues = problems(dag_id, state, tasks)
        failed |= bool(issues)
        print(f"{'FAIL' if issues else 'ok  '} {dag_id} ({state}) {' '.join(issues)}")

    new_runs = consumer_runs() - runs_before
    failed |= new_runs < 1
    print(f"{'FAIL' if new_runs < 1 else 'ok  '} {ASSET_CONSUMER} ({new_runs} new run(s))")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
