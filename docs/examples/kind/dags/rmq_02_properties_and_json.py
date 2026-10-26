"""Templated AMQP properties, JSON bodies parsed by the sensor, and binary bodies."""

from datetime import datetime

from airflow.sdk import DAG, task

from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

with DAG(
    dag_id="rmq_02_properties_and_json",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["rabbitmq"],
):
    publish_json = RabbitMQProducerOperator(
        task_id="publish_json_with_properties",
        message='{"order_id": 42, "run": "{{ run_id }}"}',
        exchange="",
        routing_key="props_queue",
        properties={
            "content_type": "application/json",
            "message_id": "{{ run_id }}",
            "correlation_id": "{{ dag.dag_id }}",
            "headers": {"source": "airflow", "try": "{{ ti.try_number }}"},
            "delivery_mode": 2,
            "priority": 5,
            "expiration": "600000",
            "app_id": "rmq_02",
        },
    )
    wait_json = RabbitMQSensor(
        task_id="wait_json",
        queue_name="props_queue",
        deserialize="json",
        poke_interval=5,
        timeout=60,
    )

    @task
    def check_json(message: dict) -> None:
        print(message)
        assert message["body_encoding"] == "json"
        assert message["body"]["order_id"] == 42
        assert message["content_type"] == "application/json"
        assert message["correlation_id"] == "rmq_02_properties_and_json"
        assert message["headers"]["source"] == "airflow"

    publish_json >> wait_json
    check_json(wait_json.output)

    # bytes are published as is; a body that isn't UTF-8 comes back base64-encoded.
    publish_binary = RabbitMQProducerOperator(
        task_id="publish_binary",
        message=b"\xff\xfe\x00binary",
        exchange="",
        routing_key="binary_queue",
        use_async=True,
    )
    wait_binary = RabbitMQSensor(
        task_id="wait_binary",
        queue_name="binary_queue",
        poke_interval=5,
        timeout=60,
    )

    @task
    def check_binary(message: dict) -> None:
        import base64

        print(message)
        assert message["body_encoding"] == "base64"
        assert base64.b64decode(message["body"]) == b"\xff\xfe\x00binary"

    publish_binary >> wait_binary
    check_binary(wait_binary.output)
