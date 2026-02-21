from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Optional, Sequence

from airflow.models import BaseOperator

if TYPE_CHECKING:
    try:
        from airflow.sdk.definitions.context import Context  # Airflow 3.x
    except ImportError:
        from airflow.utils.context import Context  # type: ignore[attr-defined]

from airflow.providers.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook


class RabbitMQProducerOperator(BaseOperator):
    """
    Airflow Operator for publishing messages to RabbitMQ.

    Supports both synchronous (blocking) and asynchronous message publishing.

    :param connection_uri: The RabbitMQ connection URI (e.g., "amqp://user:password@host:port/vhost").
                          If not provided, the connection URI will be retrieved from the Airflow connection.
    :param conn_id: The Airflow connection id to use. Default is "rabbitmq_default".
    :param message: The message to be sent to RabbitMQ.
    :param exchange: The RabbitMQ exchange name.
    :param routing_key: The routing key used for routing the message.
    :param use_async: Flag to determine whether to use async messaging. Defaults to False.
    """

    template_fields: Sequence[str] = ("message", "exchange", "routing_key")
    ui_color = "#f0e4d5"

    def __init__(
        self,
        message: str,
        exchange: str,
        routing_key: str,
        connection_uri: Optional[str] = None,
        conn_id: str = "rabbitmq_default",
        use_async: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the RabbitMQProducerOperator.

        :param message: The message to be sent to RabbitMQ.
        :param exchange: The RabbitMQ exchange name.
        :param routing_key: The routing key used for routing the message.
        :param connection_uri: The RabbitMQ connection URI (e.g., "amqp://user:password@host:port/vhost").
                              If not provided, the connection URI will be retrieved from the Airflow connection.
        :param conn_id: The Airflow connection id to use. Default is "rabbitmq_default".
        :param use_async: Flag to determine whether to use async messaging. Defaults to False.
        """
        super().__init__(**kwargs)
        self.connection_uri: Optional[str] = connection_uri
        self.conn_id: str = conn_id
        self.message: str = message
        self.exchange: str = exchange
        self.routing_key: str = routing_key
        self.use_async: bool = use_async

    def execute(self, context: Context) -> Any:
        """
        Executes the operator by publishing a message to RabbitMQ.

        Uses either synchronous (`pika`) or asynchronous (`aio-pika`) based on the `use_async` flag.

        :param context: Airflow's execution context dictionary.
        """
        hook = RabbitMQHook(connection_uri=self.connection_uri, conn_id=self.conn_id)

        try:
            if self.use_async:
                self.log.info("Publishing message asynchronously to RabbitMQ")
                asyncio.run(
                    hook.publish_async(self.message, self.exchange, self.routing_key)
                )
            else:
                self.log.info("Publishing message synchronously to RabbitMQ")
                hook.publish_sync(self.message, self.exchange, self.routing_key)
            self.log.info("Message published successfully")
        except Exception as e:
            self.log.error("Failed to publish message to RabbitMQ: %s", str(e))
            raise
