"""Mutual TLS through connection extras, sync and async, for every TLS connection.

The broker's TLS listener requires a client certificate signed by the generated CA.
The connections are created by k8s/airflow/connections.py:

- rabbitmq_tls            certificates as file paths, port defaulting to 5671
- rabbitmq_tls_pem        certificates as PEM contents
- rabbitmq_tls_alias      host not in the server certificate, fixed by ssl_server_hostname
- rabbitmq_tls_noverify   ssl_verify false: works, and logs a warning
"""

from datetime import datetime

from airflow.sdk import DAG, chain, task
from rmq_helpers import WaitForRabbitMQMessage

from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

TLS_CONNECTIONS = [
    "rabbitmq_tls",
    "rabbitmq_tls_pem",
    "rabbitmq_tls_alias",
    "rabbitmq_tls_noverify",
]

with DAG(
    dag_id="rmq_08_tls",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["rabbitmq", "tls"],
):
    steps = []
    # One chain, so no sensor consumes another step's message.
    for conn_id in TLS_CONNECTIONS:
        for mode, use_async in (("sync", False), ("async", True)):
            steps.append(
                RabbitMQProducerOperator(
                    task_id=f"{conn_id}_publish_{mode}",
                    conn_id=conn_id,
                    message=f"{conn_id} {mode} over TLS",
                    exchange="",
                    routing_key="tls_queue",
                    use_async=use_async,
                )
            )
            steps.append(
                RabbitMQSensor(
                    task_id=f"{conn_id}_sense_{mode}",
                    conn_id=conn_id,
                    queue_name="tls_queue",
                    poke_interval=5,
                    timeout=60,
                )
            )

    # The trigger consumes with aio-pika, in the triggerer.
    steps.append(
        RabbitMQProducerOperator(
            task_id="publish_for_trigger",
            conn_id="rabbitmq_tls",
            message="deferred over TLS",
            exchange="",
            routing_key="tls_queue",
        )
    )
    steps.append(
        WaitForRabbitMQMessage(
            task_id="deferred_trigger_over_tls",
            trigger_kwargs={
                "queue_name": "tls_queue",
                "conn_id": "rabbitmq_tls",
                "poll_interval": 5,
            },
        )
    )

    @task
    def check_queue_empty() -> None:
        from rmq_helpers import queue_depth

        assert queue_depth("tls_queue", conn_id="rabbitmq_tls") == 0

    steps.append(check_queue_empty())
    chain(*steps)
