"""Turn validated messages into what pika (the synchronous client) publishes."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import pika
from pika.adapters.blocking_connection import BlockingChannel

from airflow.provider.rabbitmq.messages.outgoing import OutgoingMessage
from airflow.provider.rabbitmq.messages.properties import normalize_properties


def build_pika_properties(
    properties: Optional[Mapping[str, Any]],
) -> pika.BasicProperties:
    """Build pika.BasicProperties from the ``properties`` argument."""
    return pika.BasicProperties(**normalize_properties(properties))


def publish_pika(
    channel: BlockingChannel,
    message: OutgoingMessage,
    properties: pika.BasicProperties,
) -> None:
    """Publish one message on a pika channel."""
    channel.basic_publish(
        exchange=message.exchange,
        routing_key=message.routing_key,
        body=message.body_bytes,
        properties=properties,
    )
