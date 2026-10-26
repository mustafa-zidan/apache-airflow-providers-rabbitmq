"""Exceptions raised by the provider, independent of the RabbitMQ client library."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator


class MessageNotDeliveredError(Exception):
    """
    The broker did not accept a published message.

    Raised by both publish paths with publisher confirms on, so pika's
    ``UnroutableError``/``NackError`` and aio-pika's ``PublishError``/``DeliveryError``
    can be handled the same way. The original error is the ``__cause__``.

    :param reason: ``"unroutable"`` when a mandatory message matched no queue, or
        ``"nacked"`` when the broker refused it (for example a full queue with
        ``x-overflow=reject-publish``, or a resource alarm).
    :param exchange: The exchange the message was published to.
    :param routing_key: The routing key it was published with.
    """

    UNROUTABLE = "unroutable"
    NACKED = "nacked"

    def __init__(self, reason: str, exchange: str, routing_key: str) -> None:
        self.reason = reason
        self.exchange = exchange
        self.routing_key = routing_key
        super().__init__(
            f"Message {reason} by the broker: exchange '{exchange}', "
            f"routing key '{routing_key}'"
        )


@contextmanager
def raise_not_delivered(
    exchange: str,
    routing_key: str,
    unroutable: type[Exception],
    nacked: type[Exception],
) -> Generator[None, None, None]:
    """
    Turn a client library's confirm errors into MessageNotDeliveredError.

    ``unroutable`` is checked first, since aio-pika's ``PublishError`` subclasses
    its ``DeliveryError``.

    :param exchange: The exchange the message is published to.
    :param routing_key: The routing key it is published with.
    :param unroutable: The library's error for a returned mandatory message.
    :param nacked: The library's error for a nacked message.
    """
    try:
        yield
    except unroutable as e:
        raise MessageNotDeliveredError(
            MessageNotDeliveredError.UNROUTABLE, exchange, routing_key
        ) from e
    except nacked as e:
        raise MessageNotDeliveredError(
            MessageNotDeliveredError.NACKED, exchange, routing_key
        ) from e
