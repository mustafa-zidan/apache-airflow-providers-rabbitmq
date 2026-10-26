"""Helpers shared by the rmq_* DAGs.

It lives in the plugins folder because every Airflow component, the triggerer
included, puts that folder on sys.path. The DAGs folder isn't on the triggerer's
sys.path, so RabbitMQTrigger couldn't import ``rmq_helpers.only_priority`` as its
apply_function from there.
"""

from __future__ import annotations

import json
from typing import Any

from airflow.sdk import BaseOperator

from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.messages.incoming import message_payload
from airflow.provider.rabbitmq.triggers.rabbitmq_trigger import RabbitMQTrigger


def only_priority(level: str, message: Any) -> dict[str, Any] | bool:
    """
    apply_function for RabbitMQTrigger: accept JSON messages with this priority.

    Returning False acks and skips the message; returning a dict makes it the
    event payload.
    """
    body = json.loads(message.body)
    if body.get("priority") != level:
        return False
    return {"accepted_by": "only_priority", "routing_key": message.routing_key, **body}


def drain(queue: str, conn_id: str = "rabbitmq_default") -> list[dict[str, Any]]:
    """Consume every message on the queue and return them as sensor-style payloads."""
    messages = []
    with RabbitMQHook(conn_id=conn_id).get_sync_connection_cm() as conn:
        channel = conn.channel()
        while True:
            method, properties, body = channel.basic_get(queue, auto_ack=True)
            if method is None:
                return messages
            messages.append(
                message_payload(
                    body,
                    exchange=method.exchange,
                    routing_key=method.routing_key,
                    redelivered=method.redelivered,
                    content_type=properties.content_type,
                    message_id=properties.message_id,
                    correlation_id=properties.correlation_id,
                    headers=properties.headers,
                )
                | {"app_id": properties.app_id}
            )


def queue_depth(queue: str, conn_id: str = "rabbitmq_default") -> int:
    """Number of ready messages on the queue."""
    with RabbitMQHook(conn_id=conn_id).get_sync_connection_cm() as conn:
        result = conn.channel().queue_declare(queue, passive=True)
        return result.method.message_count


class WaitForRabbitMQMessage(BaseOperator):
    """Free the worker and wait in the triggerer until the trigger yields a message."""

    def __init__(self, trigger_kwargs: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.trigger_kwargs = trigger_kwargs

    def execute(self, context: Any) -> None:
        self.defer(
            trigger=RabbitMQTrigger(**self.trigger_kwargs),
            method_name="execute_complete",
        )

    def execute_complete(self, context: Any, event: dict[str, Any]) -> dict[str, Any]:
        self.log.info("Trigger event: %s", event)
        return event
