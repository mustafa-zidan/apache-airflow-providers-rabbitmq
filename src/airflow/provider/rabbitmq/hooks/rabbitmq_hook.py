"""RabbitMQ hook with synchronous (pika) and asynchronous (aio-pika) support."""

from __future__ import annotations

import logging
import ssl
from contextlib import contextmanager
from typing import Any, Generator, Mapping, Optional, Sequence

import aio_pika
import pika
from aio_pika.abc import AbstractChannel, AbstractRobustConnection
from pika.adapters.blocking_connection import BlockingChannel, BlockingConnection

from airflow.provider.rabbitmq._compat import BaseHook
from airflow.provider.rabbitmq.adapters.aio_pika_adapter import (
    ExchangeCache,
    build_aio_pika_message,
    publish_aio_pika,
)
from airflow.provider.rabbitmq.adapters.pika_adapter import (
    build_pika_properties,
    publish_pika,
)
from airflow.provider.rabbitmq.connection import build_connection_uri
from airflow.provider.rabbitmq.exceptions import MessageNotDeliveredError
from airflow.provider.rabbitmq.messages.outgoing import (
    BatchItem,
    Body,
    OutgoingMessage,
    normalize_batch,
)
from airflow.provider.rabbitmq.messages.properties import (
    MESSAGE_PROPERTIES,
    check_property_names,
    normalize_properties,
)
from airflow.provider.rabbitmq.tls import build_ssl_context, uses_tls

# The message rules and adapters live in airflow.provider.rabbitmq.messages and
# airflow.provider.rabbitmq.adapters; they are re-exported here for code that
# imported them from the hook module.
__all__ = [
    "MESSAGE_PROPERTIES",
    "MessageNotDeliveredError",
    "RabbitMQHook",
    "build_aio_pika_message",
    "build_pika_properties",
    "check_property_names",
    "normalize_properties",
]


class RabbitMQHook(BaseHook):
    """
    Hook for interacting with RabbitMQ. Supports both synchronous and asynchronous messaging.

    This hook inherits from Airflow's BaseHook and provides methods for connecting to RabbitMQ
    and publishing messages both synchronously and asynchronously.

    Every publish method validates all of its messages before it connects, then
    publishes them in order over a single connection and channel.

    With ``confirm`` (the default) the channel uses publisher confirms, so each
    publish waits for the broker's ack and a nack raises ``MessageNotDeliveredError``.
    ``mandatory`` also raises it when a message matches no queue, instead of the
    broker dropping it.

    :param conn_id: The Airflow connection id to use. The default is "rabbitmq_default".
    :param confirm: Wait for the broker to ack each published message. Defaults to True.
    :param mandatory: Fail when a message matches no queue. Needs ``confirm``.
        Defaults to False.
    """

    conn_name_attr = "conn_id"
    default_conn_name = "rabbitmq_default"
    conn_type = "rabbitmq"
    hook_name = "RabbitMQ"

    def __init__(
        self,
        conn_id: str = default_conn_name,
        confirm: bool = True,
        mandatory: bool = False,
    ) -> None:
        """
        Initialize RabbitMQ connection settings.

        :param conn_id: The Airflow connection id to use. The default is "rabbitmq_default".
        :param confirm: Wait for the broker to ack each published message.
        :param mandatory: Fail when a message matches no queue. Needs ``confirm``.
        :raises: ValueError if ``mandatory`` is set without ``confirm``.
        """
        super().__init__()
        check_delivery_options(confirm, mandatory)
        self.conn_id = conn_id
        self.confirm = confirm
        self.mandatory = mandatory

    # Connections

    @property
    def connection_uri(self) -> str | None:
        """
        Get the RabbitMQ connection URI.

        The URI is built from the Airflow connection, see
        ``airflow.provider.rabbitmq.connection.build_connection_uri``.

        :return: The RabbitMQ connection URI.
        """
        return self._get_connection_settings()[0]

    def _get_connection_settings(self) -> tuple[str, Optional[ssl.SSLContext]]:
        """Return the URI and, when the ``ssl`` extra is set, the TLS context."""
        conn = self.get_connection(self.conn_id)
        uri = build_connection_uri(conn)
        if uri is None:
            raise ValueError(
                f"No valid connection URI found in connection {self.conn_id}. "
                "Either provide host/port/login/password or connection_uri in the connection."
            )
        if not uses_tls(conn.extra_dejson):
            return uri, None
        return uri, build_ssl_context(conn.extra_dejson)

    def _open_sync_connection(self) -> BlockingConnection:
        self.log.info("Establishing synchronous connection to RabbitMQ")
        uri, ssl_context = self._get_connection_settings()
        params = pika.URLParameters(uri)
        if ssl_context is not None:
            params.ssl_options = pika.SSLOptions(ssl_context)
        return pika.BlockingConnection(params)

    @contextmanager
    def get_sync_connection_cm(self) -> Generator[BlockingConnection, None, None]:
        """
        Context manager for synchronous RabbitMQ connections.

        :return: A BlockingConnection instance.
        :raises: ConnectionError if the connection cannot be established.
        """
        conn = self.get_sync_connection()
        try:
            yield conn
        finally:
            if conn.is_open:
                self.log.info("Closing synchronous connection to RabbitMQ")
                conn.close()

    def get_sync_connection(self) -> BlockingConnection:
        """
        Establish a synchronous connection to RabbitMQ using pika.

        :return: A BlockingConnection instance.
        :raises: ConnectionError if the connection cannot be established.
        """
        try:
            return self._open_sync_connection()
        except Exception as e:
            self.log.error("Error connecting to RabbitMQ: %s", str(e))
            raise ConnectionError(f"Failed to connect to RabbitMQ: {str(e)}") from e

    async def get_async_connection(self) -> AbstractRobustConnection:
        """
        Establish an asynchronous connection to RabbitMQ using aio-pika.

        :return: An aio_pika AbstractRobustConnection instance.
        :raises: ConnectionError if the connection cannot be established.
        """
        try:
            self.log.info("Establishing asynchronous connection to RabbitMQ")
            uri, ssl_context = self._get_connection_settings()
            return await aio_pika.connect_robust(uri, ssl_context=ssl_context)
        except Exception as e:
            self.log.error("Error connecting to RabbitMQ: %s", str(e))
            raise ConnectionError(f"Failed to connect to RabbitMQ: {str(e)}") from e

    # Synchronous publishing

    def publish_sync(
        self,
        message: Body,
        exchange: str,
        routing_key: str,
        properties: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """
        Publish a message to RabbitMQ synchronously.

        :param message: The message to be sent. A str is UTF-8 encoded.
        :param exchange: The name of the RabbitMQ exchange.
        :param routing_key: The routing key for message delivery.
        :param properties: AMQP basic properties, see ``normalize_properties``.
        :raises: ValueError if a property is unknown or invalid.
        :raises: ConnectionError if the connection cannot be established.
        :raises: MessageNotDeliveredError if the broker doesn't accept the message.
        :raises: Exception if the message cannot be published.
        """
        self._publish_sync(
            [OutgoingMessage(message, exchange, routing_key, properties)]
        )

    def publish_batch_sync(
        self,
        messages: Sequence[BatchItem],
        exchange: str = "",
        routing_key: str = "",
        properties: Optional[Mapping[str, Any]] = None,
    ) -> int:
        """
        Publish a batch of messages to RabbitMQ synchronously over a single connection and channel.

        :param messages: Sequence of messages to be sent. Items may be str, bytes, or
            dicts with 'body' (or 'message') and optional 'routing_key', 'exchange', 'properties'.
        :param exchange: Default exchange name.
        :param routing_key: Default routing key.
        :param properties: Default AMQP properties.
        :return: Number of messages published.
        :raises: ValueError if a property is unknown or invalid, or if a dict item lacks 'body'.
        :raises: TypeError if an item or body is of unsupported type.
        :raises: ConnectionError if the connection cannot be established.
        :raises: MessageNotDeliveredError if the broker doesn't accept a message; the
            messages before it were delivered.
        :raises: Exception if publishing fails.
        """
        if not messages:
            self.log.warning("No messages to publish: message list is empty.")
            return 0
        return self._publish_sync(
            normalize_batch(messages, exchange, routing_key, properties)
        )

    def _publish_sync(self, messages: Sequence[OutgoingMessage]) -> int:
        """Validate every message, then publish them all over one channel."""
        prepared = [(m, build_pika_properties(m.properties)) for m in messages]

        with self.get_sync_connection_cm() as conn:
            try:
                self.log.info(
                    "Creating channel for publishing %d message(s)", len(prepared)
                )
                channel: BlockingChannel = conn.channel()
                if self.confirm:
                    channel.confirm_delivery()
                for index, (message, pika_properties) in enumerate(prepared, start=1):
                    self._log_publish(index, len(prepared), message)
                    publish_pika(channel, message, pika_properties, self.mandatory)
                self.log.info("%d message(s) published successfully", len(prepared))
                return len(prepared)
            except Exception as e:
                self.log.error("Error publishing message: %s", str(e))
                raise

    # Asynchronous publishing

    async def publish_async(
        self,
        message: Body,
        exchange: str,
        routing_key: str,
        properties: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """
        Publish a message to RabbitMQ asynchronously.

        :param message: The message to be sent. A str is UTF-8 encoded.
        :param exchange: The name of the RabbitMQ exchange.
        :param routing_key: The routing key for message delivery.
        :param properties: AMQP basic properties, see ``normalize_properties``.
        :raises: ValueError if a property is unknown or invalid.
        :raises: ConnectionError if the connection cannot be established.
        :raises: MessageNotDeliveredError if the broker doesn't accept the message.
        :raises: Exception if the message cannot be published.
        """
        await self._publish_async(
            [OutgoingMessage(message, exchange, routing_key, properties)]
        )

    async def publish_batch_async(
        self,
        messages: Sequence[BatchItem],
        exchange: str = "",
        routing_key: str = "",
        properties: Optional[Mapping[str, Any]] = None,
    ) -> int:
        """
        Publish a batch of messages to RabbitMQ asynchronously over a single connection and channel.

        :param messages: Sequence of messages to be sent. Items may be str, bytes, or
            dicts with 'body' (or 'message') and optional 'routing_key', 'exchange', 'properties'.
        :param exchange: Default exchange name.
        :param routing_key: Default routing key.
        :param properties: Default AMQP properties.
        :return: Number of messages published.
        :raises: ValueError if a property is unknown or invalid, or if a dict item lacks 'body'.
        :raises: TypeError if an item or body is of unsupported type.
        :raises: ConnectionError if the connection cannot be established.
        :raises: MessageNotDeliveredError if the broker doesn't accept a message; the
            messages before it were delivered.
        :raises: Exception if publishing fails.
        """
        if not messages:
            self.log.warning("No messages to publish: message list is empty.")
            return 0
        return await self._publish_async(
            normalize_batch(messages, exchange, routing_key, properties)
        )

    async def _publish_async(self, messages: Sequence[OutgoingMessage]) -> int:
        """Validate every message, then publish them all over one channel."""
        prepared = [(m, build_aio_pika_message(m.body, m.properties)) for m in messages]

        connection = None
        try:
            connection = await self.get_async_connection()
            self.log.info(
                "Creating channel for publishing %d message(s) asynchronously",
                len(prepared),
            )
            channel: AbstractChannel = await connection.channel(
                publisher_confirms=self.confirm, on_return_raises=self.mandatory
            )
            exchanges = ExchangeCache(channel)
            for index, (message, outgoing) in enumerate(prepared, start=1):
                target = await exchanges.get(message.exchange)
                self._log_publish(index, len(prepared), message)
                await publish_aio_pika(target, message, outgoing, self.mandatory)
            self.log.info(
                "%d message(s) published asynchronously successfully", len(prepared)
            )
            return len(prepared)
        except Exception as e:
            self.log.error("Error publishing message asynchronously: %s", str(e))
            raise
        finally:
            if connection is not None:
                self.log.info("Closing asynchronous connection to RabbitMQ")
                await connection.close()

    def _log_publish(self, index: int, total: int, message: OutgoingMessage) -> None:
        """Log where a message goes, at DEBUG within a batch; the body is never logged."""
        self.log.log(
            logging.INFO if total == 1 else logging.DEBUG,
            "Publishing message %d/%d (%d bytes) to exchange '%s' with routing key '%s'",
            index,
            total,
            len(message.body_bytes),
            message.exchange,
            message.routing_key,
        )


def check_delivery_options(confirm: bool, mandatory: bool) -> None:
    """
    Reject ``mandatory`` without ``confirm``.

    Without confirms neither client waits for the broker, so an unroutable
    message would still be dropped without an error.

    :raises: ValueError if ``mandatory`` is set and ``confirm`` is not.
    """
    if mandatory and not confirm:
        raise ValueError("mandatory=True requires confirm=True")
