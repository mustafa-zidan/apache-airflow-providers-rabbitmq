"""Publisher confirms and mandatory routing. Every task should succeed.

The operators below show the cases that pass. The check_* tasks call the hook and
assert that the cases that must fail raise MessageNotDeliveredError; the same
cases as operators are in rmq_99_expected_failures, where they turn red.
"""

import asyncio
from datetime import datetime

from airflow.sdk import DAG, task

from airflow.provider.rabbitmq.exceptions import MessageNotDeliveredError
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

with DAG(
    dag_id="rmq_04_delivery_checks",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["rabbitmq"],
):
    for mode, use_async in (("sync", False), ("async", True)):
        # full_queue rejects every publish (x-max-length 0, reject-publish). Without
        # confirms the operator can't tell, so it succeeds and the message is lost.
        RabbitMQProducerOperator(
            task_id=f"{mode}_rejected_without_confirm_succeeds",
            message="lost",
            exchange="",
            routing_key="full_queue",
            confirm=False,
            use_async=use_async,
        )
        # Without mandatory an unroutable message is dropped by the broker.
        RabbitMQProducerOperator(
            task_id=f"{mode}_unroutable_without_mandatory_succeeds",
            message="dropped",
            exchange="unbound_exchange",
            routing_key="nowhere",
            use_async=use_async,
        )
        # A routable message passes mandatory.
        publish = RabbitMQProducerOperator(
            task_id=f"{mode}_routable_with_mandatory_succeeds",
            message="routed",
            exchange="demo_exchange",
            routing_key="demo",
            mandatory=True,
            use_async=use_async,
        )
        publish >> RabbitMQSensor(
            task_id=f"{mode}_consume_routed",
            queue_name="demo_exchange_queue",
            poke_interval=5,
            timeout=60,
        )

    @task
    def check_nack_raises() -> None:
        hook = RabbitMQHook()
        for publish in (hook.publish_sync, hook.publish_async):
            try:
                result = publish("x", exchange="", routing_key="full_queue")
                if asyncio.iscoroutine(result):
                    asyncio.run(result)
            except MessageNotDeliveredError as e:
                print(f"{publish.__name__}: {e!r}, reason={e.reason}")
                assert e.reason == "nacked"
            else:
                raise AssertionError(f"{publish.__name__} should have failed")

    @task
    def check_unroutable_raises() -> None:
        hook = RabbitMQHook(mandatory=True)
        for publish in (hook.publish_sync, hook.publish_async):
            try:
                result = publish(
                    "x", exchange="unbound_exchange", routing_key="nowhere"
                )
                if asyncio.iscoroutine(result):
                    asyncio.run(result)
            except MessageNotDeliveredError as e:
                print(f"{publish.__name__}: {e!r}, reason={e.reason}")
                assert e.reason == "unroutable"
            else:
                raise AssertionError(f"{publish.__name__} should have failed")

    check_nack_raises()
    check_unroutable_raises()
