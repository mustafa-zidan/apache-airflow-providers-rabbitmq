"""Event-driven scheduling: a message on asset_events_queue starts a DAG run (Airflow 3).

Unpause rmq_07_asset_consumer, then publish a message, by triggering
rmq_07_asset_producer or with:
    ./kind.sh publish asset_events_queue '{"hello": "asset"}'
"""

from datetime import datetime

from airflow.sdk import DAG, Asset, AssetWatcher, task

from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.provider.rabbitmq.triggers.rabbitmq_trigger import RabbitMQTrigger

asset = Asset(
    "rabbitmq_asset_events",
    watchers=[
        AssetWatcher(
            name="rabbitmq_asset_events_watcher",
            trigger=RabbitMQTrigger(queue_name="asset_events_queue", poll_interval=5),
        )
    ],
)

with DAG(
    dag_id="rmq_07_asset_consumer",
    start_date=datetime(2026, 1, 1),
    schedule=[asset],
    catchup=False,
    tags=["rabbitmq"],
):

    @task
    def show_triggering_message(triggering_asset_events=None) -> None:
        for event in triggering_asset_events[asset]:
            # The trigger's payload is in the asset event's extra.
            print("asset event extra:", event.extra)

    show_triggering_message()

with DAG(
    dag_id="rmq_07_asset_producer",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["rabbitmq"],
):
    RabbitMQProducerOperator(
        task_id="publish_asset_event",
        message='{"from": "rmq_07_asset_producer", "run": "{{ run_id }}"}',
        exchange="",
        routing_key="asset_events_queue",
        properties={"content_type": "application/json"},
    )
