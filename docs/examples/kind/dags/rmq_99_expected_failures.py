"""Every task named fail_* should end red. Open its log to see the error.

retries=0, so each fails on the first try.
"""

from datetime import datetime

from airflow.sdk import DAG

from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

with DAG(
    dag_id="rmq_99_expected_failures",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    default_args={"retries": 0},
    tags=["rabbitmq"],
):
    for mode, use_async in (("sync", False), ("async", True)):
        # MessageNotDeliveredError: Message nacked by the broker
        RabbitMQProducerOperator(
            task_id=f"fail_{mode}_nacked_by_full_queue",
            message="rejected",
            exchange="",
            routing_key="full_queue",
            use_async=use_async,
        )
        # MessageNotDeliveredError: Message unroutable by the broker
        RabbitMQProducerOperator(
            task_id=f"fail_{mode}_unroutable_with_mandatory",
            message="unroutable",
            exchange="unbound_exchange",
            routing_key="nowhere",
            mandatory=True,
            use_async=use_async,
        )
        # The exchange is declared passively, so a missing one fails (404 NOT_FOUND)
        RabbitMQProducerOperator(
            task_id=f"fail_{mode}_missing_exchange",
            message="nowhere",
            exchange="no_such_exchange",
            routing_key="x",
            use_async=use_async,
        )

    # ValueError before connecting
    RabbitMQProducerOperator(
        task_id="fail_invalid_property",
        message="x",
        exchange="",
        routing_key="demo_queue",
        properties={"priority": "high"},
    )

    # The publish succeeds; the sensor fails and leaves the message on the queue.
    RabbitMQProducerOperator(
        task_id="publish_big_message",
        message="x" * 1000,
        exchange="",
        routing_key="big_queue",
    ) >> RabbitMQSensor(
        task_id="fail_sensor_max_xcom_bytes",
        queue_name="big_queue",
        max_xcom_bytes=100,
        poke_interval=5,
        timeout=60,
    )
    RabbitMQProducerOperator(
        task_id="publish_not_json",
        message="this is not json",
        exchange="",
        routing_key="not_json_queue",
    ) >> RabbitMQSensor(
        task_id="fail_sensor_deserialize_json",
        queue_name="not_json_queue",
        deserialize="json",
        poke_interval=5,
        timeout=60,
    )

    # ConnectionError: the broker requires a client certificate
    RabbitMQProducerOperator(
        task_id="fail_tls_without_client_cert",
        conn_id="rabbitmq_tls_no_client_cert",
        message="x",
        exchange="",
        routing_key="tls_queue",
    )
    # ConnectionError ... The ssl extra must be true or false, got 'yes'
    RabbitMQProducerOperator(
        task_id="fail_tls_string_flag",
        conn_id="rabbitmq_tls_string_flag",
        message="x",
        exchange="",
        routing_key="tls_queue",
    )
