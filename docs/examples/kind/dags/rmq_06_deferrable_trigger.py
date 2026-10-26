"""Defer a task on RabbitMQTrigger, bound to a topic exchange and filtered by apply_function."""

from datetime import datetime

from airflow.sdk import DAG, task
from rmq_helpers import WaitForRabbitMQMessage

from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)

with DAG(
    dag_id="rmq_06_deferrable_trigger",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["rabbitmq"],
):
    # trigger_queue is bound to the topic exchange "events" with "order.*". The
    # trigger skips (acks) messages only_priority rejects, and yields the first
    # high-priority one, with only_priority's return value as the payload.
    wait = WaitForRabbitMQMessage(
        task_id="wait_for_high_priority_order",
        trigger_kwargs={
            "queue_name": "trigger_queue",
            "exchange_type": "topic",
            "exchange_name": "events",
            "routing_key": "order.*",
            "apply_function": "rmq_helpers.only_priority",
            "apply_function_args": ["high"],
            "poll_interval": 5,
        },
    )

    publish = RabbitMQProducerOperator(
        task_id="publish_events",
        message=[
            {"body": '{"id": 1, "priority": "low"}', "routing_key": "order.created"},
            # Doesn't match "order.*": the exchange routes it nowhere.
            {"body": '{"id": 2, "priority": "high"}', "routing_key": "invoice.paid"},
            {"body": '{"id": 3, "priority": "high"}', "routing_key": "order.cancelled"},
        ],
        exchange="events",
        routing_key="unused",
    )

    @task
    def check_event(event: dict) -> None:
        from rmq_helpers import queue_depth

        print(event)
        assert event["accepted_by"] == "only_priority"
        assert event["id"] == 3 and event["routing_key"] == "order.cancelled"
        assert queue_depth("trigger_queue") == 0

    check_event(wait.output)
