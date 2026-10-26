"""Operator for publishing messages to RabbitMQ."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Optional, Sequence, Union, cast

from airflow.models import BaseOperator

from airflow.provider.rabbitmq.hooks.rabbitmq_hook import (
    RabbitMQHook,
    check_delivery_options,
)
from airflow.provider.rabbitmq.messages.outgoing import (
    BatchItem,
    Body,
    check_message_property_names,
)

if TYPE_CHECKING:
    from airflow.provider.rabbitmq._compat import Context


class RabbitMQProducerOperator(BaseOperator):
    """
    Airflow Operator for publishing messages to RabbitMQ.

    Supports both single message and batch message publishing, synchronously (blocking)
    or asynchronously.

    When ``message`` is a list or sequence, messages are published in order over a single
    connection and channel. Individual items can be ``str``, ``bytes``, or ``dict`` containing
    ``body`` (or ``message``) and optional ``routing_key``, ``exchange``, and ``properties``
    overrides. An item's ``properties`` are merged over ``properties`` key by key; set a
    key to None to unset it for that item.

    If a template renders to a list (e.g. from upstream XCom), ensure the DAG has
    ``render_template_as_native_obj=True``.

    :param conn_id: The Airflow connection id to use. Default is "rabbitmq_default".
    :param message: The message or sequence of messages to be sent to RabbitMQ.
        Can be str, bytes, or a list/tuple of str, bytes, or dicts.
    :param exchange: The RabbitMQ exchange name (or default exchange for batch items).
    :param routing_key: The routing key used for routing the message (or default for batch items).
    :param use_async: Flag to determine whether to use async messaging. Defaults to False.
    :param properties: AMQP basic properties (content_type, headers, delivery_mode,
        priority, correlation_id, expiration in milliseconds, ...). Templated.
        Unknown keys raise ValueError.
    :param confirm: Wait for the broker to ack each message, and fail the task with
        ``MessageNotDeliveredError`` when it nacks one. Defaults to True.
    :param mandatory: Also fail the task when a message matches no queue, instead
        of the broker dropping it. Needs ``confirm``. Defaults to False.
    """

    template_fields: Sequence[str] = (
        "message",
        "exchange",
        "routing_key",
        "properties",
    )
    ui_color = "#f0e4d5"

    def __init__(
        self,
        message: Union[Body, Sequence[BatchItem]],
        exchange: str,
        routing_key: str,
        conn_id: str = "rabbitmq_default",
        use_async: bool = False,
        properties: Optional[dict[str, Any]] = None,
        confirm: bool = True,
        mandatory: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the RabbitMQProducerOperator.

        :param message: The message or sequence of messages to be sent to RabbitMQ.
        :param exchange: The RabbitMQ exchange name.
        :param routing_key: The routing key used for routing the message.
        :param conn_id: The Airflow connection id to use. Default is "rabbitmq_default".
        :param use_async: Flag to determine whether to use async messaging. Defaults to False.
        :param properties: AMQP basic properties for the message.
        :param confirm: Wait for the broker to ack each message. Defaults to True.
        :param mandatory: Fail when a message matches no queue. Defaults to False.
        """
        super().__init__(**kwargs)
        # Values can be templates, so only the names are checked here; the hook
        # validates the rendered values.
        check_message_property_names(message, properties)
        check_delivery_options(confirm, mandatory)
        self.conn_id: str = conn_id
        self.message: Union[Body, Sequence[BatchItem]] = message
        self.exchange: str = exchange
        self.routing_key: str = routing_key
        self.use_async: bool = use_async
        self.properties: Optional[dict[str, Any]] = properties
        self.confirm: bool = confirm
        self.mandatory: bool = mandatory

    def execute(self, context: Context) -> int:
        """
        Executes the operator by publishing message(s) to RabbitMQ.

        Uses either synchronous (`pika`) or asynchronous (`aio-pika`) based on the `use_async` flag.

        :param context: Airflow's execution context dictionary.
        :return: Number of messages published.
        """
        hook = RabbitMQHook(conn_id=self.conn_id)
        message = self.message
        if isinstance(message, (str, bytes)):
            return self._publish_one(hook, message)
        if isinstance(message, Sequence):
            # mypy keeps bytes in the union (bytearray promotes to bytes), so the
            # str/bytes case handled above is cast away here.
            return self._publish_batch(hook, cast(Sequence[BatchItem], message))
        raise TypeError(
            f"message must be str, bytes, or a sequence of messages, got {type(message).__name__}"
        )

    @property
    def _mode(self) -> str:
        return "asynchronously" if self.use_async else "synchronously"

    def _publish_one(self, hook: RabbitMQHook, message: Body) -> int:
        """Publish a single str or bytes message."""
        self.log.info("Publishing message %s to RabbitMQ", self._mode)
        try:
            if self.use_async:
                asyncio.run(
                    hook.publish_async(
                        message,
                        self.exchange,
                        self.routing_key,
                        properties=self.properties,
                        confirm=self.confirm,
                        mandatory=self.mandatory,
                    )
                )
            else:
                hook.publish_sync(
                    message,
                    self.exchange,
                    self.routing_key,
                    properties=self.properties,
                    confirm=self.confirm,
                    mandatory=self.mandatory,
                )
        except Exception as e:
            self.log.error("Failed to publish message to RabbitMQ: %s", str(e))
            raise
        self.log.info("Message published successfully")
        return 1

    def _publish_batch(self, hook: RabbitMQHook, messages: Sequence[BatchItem]) -> int:
        """Publish a sequence of messages over one connection."""
        if len(messages) == 0:
            self.log.warning("No messages to publish: message list is empty.")
            return 0
        self.log.info(
            "Publishing %d message(s) %s to RabbitMQ", len(messages), self._mode
        )
        try:
            if self.use_async:
                count = asyncio.run(
                    hook.publish_batch_async(
                        messages,
                        self.exchange,
                        self.routing_key,
                        properties=self.properties,
                        confirm=self.confirm,
                        mandatory=self.mandatory,
                    )
                )
            else:
                count = hook.publish_batch_sync(
                    messages,
                    self.exchange,
                    self.routing_key,
                    properties=self.properties,
                    confirm=self.confirm,
                    mandatory=self.mandatory,
                )
        except Exception as e:
            self.log.error("Failed to publish batch messages to RabbitMQ: %s", str(e))
            raise
        self.log.info("Batch of %d message(s) published successfully", count)
        return count
