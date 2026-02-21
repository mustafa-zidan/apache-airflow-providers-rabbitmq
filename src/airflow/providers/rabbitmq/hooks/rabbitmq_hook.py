from contextlib import contextmanager
from typing import Generator, Optional

import aio_pika
import pika
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

try:
    # Prefer Airflow 2.x base hook path for broader compatibility and easier test mocking
    from airflow.hooks.base import BaseHook as _AFBaseHook
except ImportError:
    from airflow.sdk.bases.hook import BaseHook as _AFBaseHook

BaseHook = _AFBaseHook
from pika.adapters.blocking_connection import BlockingConnection, BlockingChannel


class RabbitMQHook(BaseHook):
    """
    Hook for interacting with RabbitMQ. Supports both synchronous and asynchronous messaging.

    This hook inherits from Airflow's BaseHook and provides methods for connecting to RabbitMQ
    and publishing messages both synchronously and asynchronously.

    :param connection_uri: RabbitMQ connection string (e.g., "amqp://user:password@host:port/vhost").
                          If not provided, it will be retrieved from the Airflow connection.
    :param conn_id: The Airflow connection id to use. The default is "rabbitmq_default".
    """

    conn_name_attr = "conn_id"
    default_conn_name = "rabbitmq_default"
    conn_type = "rabbitmq"
    hook_name = "RabbitMQ"

    def __init__(
        self, connection_uri: Optional[str] = None, conn_id: str = default_conn_name
    ) -> None:
        """
        Initialize RabbitMQ connection settings.

        :param connection_uri: RabbitMQ connection string (e.g., "amqp://user:password@host:port/vhost").
                              If not provided, it will be retrieved from the Airflow connection.
        :param conn_id: The Airflow connection id to use. The default is "rabbitmq_default".
        """
        super().__init__()
        self.conn_id = conn_id
        self._connection_uri: Optional[str] = connection_uri

    @property
    def connection_uri(self) -> str | None:
        """
        Get the RabbitMQ connection URI.

        If a connection_uri was provided during initialization, it will be used.
        Otherwise, the connection URI will be retrieved from the Airflow connection.

        :return: The RabbitMQ connection URI.
        """
        if self._connection_uri:
            return self._connection_uri

        conn = self.get_connection(self.conn_id)
        if conn.host and conn.port:
            user_pass = ""
            if conn.login and conn.password:
                user_pass = f"{conn.login}:{conn.password}@"

            vhost = conn.schema or ""
            if vhost:
                vhost = f"/{vhost}"

            return f"amqp://{user_pass}{conn.host}:{conn.port}{vhost}"
        elif conn.extra_dejson.get("connection_uri"):
            return conn.extra_dejson.get("connection_uri")
        else:
            raise ValueError(
                f"No valid connection URI found in connection {self.conn_id}. "
                "Either provide host/port/login/password or connection_uri in the connection."
            )

    @contextmanager
    def get_sync_connection_cm(self) -> Generator[BlockingConnection, None, None]:
        """
        Context manager for synchronous RabbitMQ connections.

        :return: A BlockingConnection instance.
        :raises: ConnectionError if the connection cannot be established.
        """
        conn = None
        try:
            self.log.info("Establishing synchronous connection to RabbitMQ")
            params = pika.URLParameters(self.connection_uri)
            conn = pika.BlockingConnection(params)
            yield conn
        except Exception as e:
            self.log.error("Error connecting to RabbitMQ: %s", str(e))
            raise ConnectionError(f"Failed to connect to RabbitMQ: {str(e)}") from e
        finally:
            if conn is not None and conn.is_open:
                self.log.info("Closing synchronous connection to RabbitMQ")
                conn.close()

    def get_sync_connection(self) -> BlockingConnection:
        """
        Establish a synchronous connection to RabbitMQ using pika.

        :return: A BlockingConnection instance.
        :raises: ConnectionError if the connection cannot be established.
        """
        try:
            self.log.info("Establishing synchronous connection to RabbitMQ")
            params = pika.URLParameters(self.connection_uri)
            return pika.BlockingConnection(params)
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
            return await aio_pika.connect_robust(self.connection_uri)
        except Exception as e:
            self.log.error("Error connecting to RabbitMQ: %s", str(e))
            raise ConnectionError(f"Failed to connect to RabbitMQ: {str(e)}") from e

    def publish_sync(self, message: str, exchange: str, routing_key: str) -> None:
        """
        Publish a message to RabbitMQ synchronously.

        :param message: The message to be sent.
        :param exchange: The name of the RabbitMQ exchange.
        :param routing_key: The routing key for message delivery.
        :raises: ConnectionError if the connection cannot be established.
        :raises: Exception if the message cannot be published.
        """
        with self.get_sync_connection_cm() as conn:
            try:
                self.log.info("Creating channel for publishing message")
                channel: BlockingChannel = conn.channel()

                self.log.info(
                    "Publishing message to exchange '%s' with routing key '%s'",
                    exchange,
                    routing_key,
                )
                channel.basic_publish(
                    exchange=exchange, routing_key=routing_key, body=message.encode()
                )
                self.log.info("Message published successfully")
            except Exception as e:
                self.log.error("Error publishing message: %s", str(e))
                raise

    async def publish_async(
        self, message: str, exchange: str, routing_key: str
    ) -> None:
        """
        Publish a message to RabbitMQ asynchronously.

        :param message: The message to be sent.
        :param exchange: The name of the RabbitMQ exchange.
        :param routing_key: The routing key for message delivery.
        :raises: ConnectionError if the connection cannot be established.
        :raises: Exception if the message cannot be published.
        """
        connection = None
        try:
            connection = await self.get_async_connection()
            self.log.info("Creating channel for publishing message asynchronously")
            channel: AbstractChannel = await connection.channel()

            self.log.info(
                "Publishing message asynchronously to exchange '%s' with routing key '%s'",
                exchange,
                routing_key,
            )
            await channel.default_exchange.publish(
                aio_pika.Message(body=message.encode()), routing_key=routing_key
            )
            self.log.info("Message published successfully")
        except Exception as e:
            self.log.error("Error publishing message asynchronously: %s", str(e))
            raise
        finally:
            if connection is not None:
                self.log.info("Closing asynchronous connection to RabbitMQ")
                await connection.close()
