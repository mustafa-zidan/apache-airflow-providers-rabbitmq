from datetime import datetime

from airflow import DAG
from airflow.providers.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.providers.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

with DAG(
    dag_id="rabbitmq_example_dag",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
) as dag:

    # 1. Publish a message to RabbitMQ
    publish_message = RabbitMQProducerOperator(
        task_id="publish_message",
        message="Hello from Airflow! The time is {{ ts }}",
        exchange="",
        routing_key="my_queue",
        conn_id="rabbitmq_default",
    )

    # 2. Wait for a message in the same (or another) queue
    wait_for_message = RabbitMQSensor(
        task_id="wait_for_message",
        queue="my_queue",
        poke_interval=10,
        timeout=300,
        conn_id="rabbitmq_default",
    )

    publish_message >> wait_for_message
