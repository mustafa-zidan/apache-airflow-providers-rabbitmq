"""Publish sync and async, through the default and a named exchange, and sense each message."""

from datetime import datetime

from airflow.sdk import DAG

from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

with DAG(
    dag_id="rmq_01_publish_and_sense",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["rabbitmq"],
):
    for mode, use_async in (("sync", False), ("async", True)):
        # Default exchange: the routing key is the queue name.
        publish_default = RabbitMQProducerOperator(
            task_id=f"publish_{mode}_default_exchange",
            message=f"{mode} via the default exchange in {{{{ run_id }}}}",
            exchange="",
            routing_key="demo_queue",
            use_async=use_async,
        )
        wait_default = RabbitMQSensor(
            task_id=f"wait_{mode}_default_exchange",
            queue_name="demo_queue",
            poke_interval=5,
            timeout=60,
        )
        publish_default >> wait_default

        # demo_exchange routes "demo" to demo_exchange_queue.
        publish_named = RabbitMQProducerOperator(
            task_id=f"publish_{mode}_named_exchange",
            message=f"{mode} via demo_exchange in {{{{ run_id }}}}",
            exchange="demo_exchange",
            routing_key="demo",
            use_async=use_async,
        )
        wait_named = RabbitMQSensor(
            task_id=f"wait_{mode}_named_exchange",
            queue_name="demo_exchange_queue",
            poke_interval=5,
            timeout=60,
        )
        publish_named >> wait_named
