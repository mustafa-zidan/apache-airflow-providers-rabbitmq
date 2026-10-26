"""Turn validated messages into what pika (the synchronous client) publishes."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import NackError, UnroutableError

from airflow.provider.rabbitmq.exceptions import raise_not_delivered
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
    mandatory: bool = False,
) -> None:
    """
    Publish one message on a pika channel.

    On a channel in confirm mode this waits for the broker's ack.

    :raises: MessageNotDeliveredError if the broker nacks the message, or returns
        it as unroutable when ``mandatory`` is set.
    """
    with raise_not_delivered(
        message.exchange, message.routing_key, UnroutableError, NackError
    ):
        channel.basic_publish(
            exchange=message.exchange,
            routing_key=message.routing_key,
            body=message.body_bytes,
            properties=properties,
            mandatory=mandatory,
        )
