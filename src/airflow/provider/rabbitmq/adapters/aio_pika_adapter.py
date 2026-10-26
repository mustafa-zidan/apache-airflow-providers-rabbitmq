"""Turn validated messages into what aio-pika (the asynchronous client) publishes."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping, Optional

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractExchange
from aio_pika.exceptions import DeliveryError, PublishError

from airflow.provider.rabbitmq.exceptions import MessageNotDeliveredError
from airflow.provider.rabbitmq.messages.outgoing import Body, OutgoingMessage, to_bytes
from airflow.provider.rabbitmq.messages.properties import normalize_properties


def build_aio_pika_message(
    message: Body, properties: Optional[Mapping[str, Any]]
) -> aio_pika.Message:
    """Build an aio_pika.Message; aio_pika takes expiration in seconds, not ms."""
    props: dict[str, Any] = normalize_properties(properties)
    if "expiration" in props:
        props["expiration"] = timedelta(milliseconds=int(props["expiration"]))
    if "delivery_mode" in props:
        props["delivery_mode"] = aio_pika.DeliveryMode(props["delivery_mode"])
    return aio_pika.Message(body=to_bytes(message), **props)


async def resolve_exchange(channel: AbstractChannel, name: str) -> AbstractExchange:
    """
    Return the exchange to publish to; an empty name is the default exchange.

    A named exchange is declared passively, so a missing one raises instead of the
    broker silently dropping the message.
    """
    if not name:
        return channel.default_exchange
    return await channel.get_exchange(name, ensure=True)


async def publish_aio_pika(
    exchange: AbstractExchange,
    message: OutgoingMessage,
    outgoing: aio_pika.Message,
    mandatory: bool = False,
) -> None:
    """
    Publish one message on an aio-pika exchange.

    On a channel with publisher confirms this waits for the broker's ack.

    :raises: MessageNotDeliveredError if the broker nacks the message, or returns
        it as unroutable when ``mandatory`` is set.
    """
    try:
        await exchange.publish(
            outgoing, routing_key=message.routing_key, mandatory=mandatory
        )
    except PublishError as e:  # a DeliveryError raised for a Basic.Return
        raise MessageNotDeliveredError(
            MessageNotDeliveredError.UNROUTABLE, message.exchange, message.routing_key
        ) from e
    except DeliveryError as e:
        raise MessageNotDeliveredError(
            MessageNotDeliveredError.NACKED, message.exchange, message.routing_key
        ) from e


class ExchangeCache:  # pylint: disable=too-few-public-methods
    """Resolve each exchange once per channel, for batches spanning exchanges."""

    def __init__(self, channel: AbstractChannel) -> None:
        self._channel = channel
        self._exchanges: dict[str, AbstractExchange] = {}

    async def get(self, name: str) -> AbstractExchange:
        """Return the exchange, resolving it on first use."""
        if name not in self._exchanges:
            self._exchanges[name] = await resolve_exchange(self._channel, name)
        return self._exchanges[name]
