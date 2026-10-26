"""Exceptions raised by the provider, independent of the RabbitMQ client library."""

from __future__ import annotations


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
