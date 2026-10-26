"""Sensor peeking (auto_ack=False) and reschedule mode."""

import time
from datetime import datetime

from airflow.sdk import DAG, task

from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

with DAG(
    dag_id="rmq_05_sensor_modes",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["rabbitmq"],
):
    # Peek: the first sensor returns the message and requeues it, so the second
    # sensor gets the same message again, marked redelivered, and removes it.
    publish = RabbitMQProducerOperator(
        task_id="publish_for_peek",
        message="peek at me {{ run_id }}",
        exchange="",
        routing_key="peek_queue",
    )
    peek = RabbitMQSensor(
        task_id="peek_without_ack",
        queue_name="peek_queue",
        auto_ack=False,
        poke_interval=5,
        timeout=60,
    )
    consume = RabbitMQSensor(
        task_id="consume_with_ack",
        queue_name="peek_queue",
        poke_interval=5,
        timeout=60,
    )

    @task
    def check_peek(peeked: dict, consumed: dict) -> None:
        from rmq_helpers import queue_depth

        print("peeked:", peeked)
        print("consumed:", consumed)
        assert peeked["body"] == consumed["body"]
        assert consumed["redelivered"] is True
        assert queue_depth("peek_queue") == 0

    publish >> peek >> consume
    check_peek(peek.output, consume.output)

    # Reschedule mode frees the worker slot between pokes: the task shows as
    # "up_for_reschedule" until a message arrives about 30 seconds later.
    RabbitMQSensor(
        task_id="wait_in_reschedule_mode",
        queue_name="reschedule_queue",
        mode="reschedule",
        poke_interval=10,
        timeout=300,
    )

    @task
    def publish_later() -> None:
        time.sleep(30)
        RabbitMQHook().publish_sync(
            "arrived late", exchange="", routing_key="reschedule_queue"
        )

    publish_later()
