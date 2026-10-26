"""Publish a list of messages over one connection, with per-item overrides."""

from datetime import datetime

from airflow.sdk import DAG, task

from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)

BATCH = [
    "a plain string",
    b"some bytes",
    # Item overrides: routing key, and properties merged over the operator's
    {"body": "routed elsewhere", "routing_key": "batch_other_queue"},
    {"body": '{"x": 1}', "properties": {"content_type": "application/json"}},
]

with DAG(
    dag_id="rmq_03_batch",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["rabbitmq"],
):
    publishers = [
        RabbitMQProducerOperator(
            task_id=f"publish_batch_{mode}",
            message=BATCH,
            exchange="",
            routing_key="batch_queue",
            properties={"app_id": f"rmq_03_{mode}"},
            use_async=use_async,
        )
        for mode, use_async in (("sync", False), ("async", True))
    ]

    @task
    def check_batches(sync_count: int, async_count: int) -> None:
        from rmq_helpers import drain

        # The operator returns how many messages it published.
        assert sync_count == async_count == len(BATCH)

        main = drain("batch_queue")
        other = drain("batch_other_queue")
        print("batch_queue:", main)
        print("batch_other_queue:", other)
        assert len(main) == 6 and len(other) == 2
        assert {m["app_id"] for m in main + other} == {"rmq_03_sync", "rmq_03_async"}
        json_items = [m for m in main if m["content_type"] == "application/json"]
        assert len(json_items) == 2

    check_batches(publishers[0].output, publishers[1].output)
