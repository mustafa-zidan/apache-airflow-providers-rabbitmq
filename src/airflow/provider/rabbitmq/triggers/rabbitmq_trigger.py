"""Trigger that waits for a message on a RabbitMQ queue and yields it as an event."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Sequence

from aio_pika import ExchangeType
from aio_pika.abc import (
    AbstractChannel,
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustConnection,
)
from airflow.triggers.base import TriggerEvent
from asgiref.sync import sync_to_async

from airflow.provider.rabbitmq._compat import (
    BaseEventTrigger,
    import_string,
    unwrap_serialized,
)
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.messages.incoming import message_payload

# Options read from **kwargs, with their defaults. Other keys are logged and ignored.
KWARG_OPTIONS: dict[str, Any] = {
    "durable": True,
    "exclusive": False,
    "passive": False,
    "auto_delete": False,
    "internal": False,
    "timeout": None,
    "arguments_queue": None,
    "arguments_exchange": None,
    "arguments_bind": None,
}


class RabbitMQTrigger(BaseEventTrigger):
    """
    Wait for a message on a RabbitMQ queue, yield it as an event, and finish.

    Both ``AssetWatcher`` (restarted by the triggerer after each event) and the
    deferrable sensor use this class, so it must never yield an error event (a
    watcher turns every event into a DAG run) or requeue a message it has yielded.

    The message is acked before the event is yielded: delivery is at-most-once.
    The payload is the dict ``message_payload`` builds, the same one
    ``RabbitMQSensor`` pushes to XCom.

    :param queue_name: The queue to consume from.
    :param conn_id: The Airflow connection id. Default is "rabbitmq_default".
    :param exchange_type: "queue" to consume ``queue_name`` directly, or an exchange
        type such as "direct" or "topic".
    :param exchange_name: The exchange to bind the queue to; required unless
        ``exchange_type`` is "queue".
    :param routing_key: The binding key. Default "#".
    :param requeue_on_error: Requeue once when ``apply_function`` raises; a second
        failure rejects the message (to the dead-letter exchange, if there is one).
    :param poll_interval: Seconds between connection attempts.
    :param apply_function: Dotted path to ``f(*args, message, **kwargs)``,
        importable from the triggerer. A falsy return acks and skips the message.
        ``True`` yields the standard payload; any other truthy return is yielded
        as the event payload instead, so it must be JSON-serializable.
    :param apply_function_args: Positional arguments for ``apply_function``.
    :param apply_function_kwargs: Keyword arguments for ``apply_function``.
    :param kwargs: Queue, exchange and binding options listed in ``KWARG_OPTIONS``.
        Other keys are logged and ignored.
    """

    def __init__(
        self,
        queue_name: str,
        conn_id: str = "rabbitmq_default",
        exchange_type: str = "queue",  # queue, fanout, direct, topic
        exchange_name: Optional[str] = None,
        routing_key: Optional[str] = None,
        requeue_on_error: bool = True,
        poll_interval: int = 10,
        apply_function: Optional[str] = None,
        apply_function_args: Optional[Sequence[Any]] = None,
        apply_function_kwargs: Optional[dict[Any, Any]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[no-untyped-call]
        unknown = sorted(set(kwargs) - set(KWARG_OPTIONS))
        if unknown:
            self.log.warning(
                "RabbitMQTrigger ignores unknown arguments: %s", ", ".join(unknown)
            )

        self._connection: Optional[AbstractRobustConnection] = None
        self.conn_id = conn_id
        self.queue_name = queue_name
        self.requeue_on_error = requeue_on_error
        self.poll_interval = poll_interval

        self.apply_function = apply_function
        self.apply_function_args = list(unwrap_serialized(apply_function_args) or [])
        self.apply_function_kwargs = dict(
            unwrap_serialized(apply_function_kwargs) or {}
        )

        ex_type_str = str(exchange_type).lower() if exchange_type else "queue"
        if ex_type_str == "queue":
            if exchange_name or routing_key:
                raise ValueError(
                    "exchange_name and routing_key need an exchange_type other than 'queue'"
                )
            self.exchange_name = ""
            self.exchange_type = "queue"
            self.routing_key = ""
        else:
            if not exchange_name:
                raise ValueError(f"exchange_type={exchange_type!r} needs exchange_name")
            self.exchange_name = exchange_name
            # Store the value aio-pika accepts; raises on unknown types.
            self.exchange_type = ExchangeType(ex_type_str).value
            # Store the key that gets bound, so serialize() matches the binding.
            self.routing_key = routing_key or "#"

        options = {**KWARG_OPTIONS, **unwrap_serialized(kwargs)}
        self.durable: bool = options["durable"]
        self.exclusive: bool = options["exclusive"]
        self.passive: bool = options["passive"]
        self.auto_delete: bool = options["auto_delete"]
        self.internal: bool = options["internal"]
        self.timeout: Optional[float] = options["timeout"]
        self.arguments_queue: Optional[dict[str, Any]] = options["arguments_queue"]
        self.arguments_exchange: Optional[dict[str, Any]] = options[
            "arguments_exchange"
        ]
        self.arguments_bind: Optional[dict[str, Any]] = options["arguments_bind"]

    def serialize(self) -> tuple[str, dict[str, Any]]:
        """Serialize the trigger. Unknown kwargs are not stored."""
        return (
            f"{self.__class__.__module__}.{self.__class__.__qualname__}",
            {
                "queue_name": self.queue_name,
                "conn_id": self.conn_id,
                "exchange_type": self.exchange_type,
                "exchange_name": self.exchange_name,
                "routing_key": self.routing_key,
                "requeue_on_error": self.requeue_on_error,
                "poll_interval": self.poll_interval,
                "apply_function": self.apply_function,
                "apply_function_args": self.apply_function_args,
                "apply_function_kwargs": self.apply_function_kwargs,
                "durable": self.durable,
                "exclusive": self.exclusive,
                "passive": self.passive,
                "auto_delete": self.auto_delete,
                "internal": self.internal,
                "timeout": self.timeout,
                "arguments_queue": self.arguments_queue,
                "arguments_exchange": self.arguments_exchange,
                "arguments_bind": self.arguments_bind,
            },
        )

    async def _connect(self) -> AbstractRobustConnection:
        """Connect, retrying every poll_interval."""
        hook = RabbitMQHook(conn_id=self.conn_id)
        while True:
            try:
                connection = await hook.get_async_connection()
            except Exception as e:  # pylint: disable=broad-except
                # Retry rather than yield an error event, which a watcher would turn
                # into a DAG run. Log only the exception type: the URI and the error
                # text can hold the password, percent-encoded past the secrets masker.
                self.log.warning(
                    "Cannot connect to RabbitMQ (conn_id=%s): %s. Retrying in %ss",
                    self.conn_id,
                    type(e).__name__,
                    self.poll_interval,
                )
                await asyncio.sleep(self.poll_interval)
                continue
            self.log.info("Connected to RabbitMQ (conn_id=%s)", self.conn_id)
            return connection

    async def declare_queue(self, channel: AbstractChannel) -> AbstractQueue:
        """Declare the queue, and the exchange and binding when exchange_name is set."""
        queue = await channel.declare_queue(
            name=self.queue_name,
            durable=self.durable,
            exclusive=self.exclusive,
            passive=self.passive,
            auto_delete=self.auto_delete,
            arguments=self.arguments_queue,
            timeout=self.timeout,
        )

        if self.exchange_name:
            exchange = await channel.declare_exchange(
                name=self.exchange_name,
                type=self.exchange_type,
                durable=self.durable,
                auto_delete=self.auto_delete,
                internal=self.internal,
                passive=self.passive,
                arguments=self.arguments_exchange,
                timeout=self.timeout,
            )
            await queue.bind(
                exchange=exchange,
                routing_key=self.routing_key,
                arguments=self.arguments_bind,
                timeout=self.timeout,
            )

        return queue

    def _load_apply_function(
        self,
    ) -> Optional[Callable[[AbstractIncomingMessage], Awaitable[Any]]]:
        if not self.apply_function:
            return None
        func = partial(
            import_string(self.apply_function),
            *self.apply_function_args,
            **self.apply_function_kwargs,
        )
        return sync_to_async(func)

    @staticmethod
    def _to_payload(message: AbstractIncomingMessage) -> dict[str, Any]:
        """Build the event payload. Airflow stores it as JSON."""
        return message_payload(
            message.body,
            exchange=message.exchange,
            routing_key=message.routing_key,
            redelivered=message.redelivered,
            content_type=message.content_type,
            message_id=message.message_id,
            correlation_id=message.correlation_id,
            headers=message.headers,
        )

    async def run(self) -> AsyncIterator[TriggerEvent]:
        """Consume until apply_function accepts a message, yield it and return."""
        accept = self._load_apply_function()
        self._connection = await self._connect()
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=1)
        queue = await self.declare_queue(channel)

        async with queue.iterator() as messages:
            async for message in messages:
                # A message that fails twice is rejected, so it can't loop forever.
                async with message.process(
                    requeue=self.requeue_on_error, reject_on_redelivered=True
                ):
                    result = True if accept is None else await accept(message)
                    if not result:
                        # Acked on exit, with no sleep before the next message.
                        continue
                    # As in Kafka's AwaitMessageTrigger, the function's return
                    # value is the payload; a plain True keeps the default one.
                    payload = self._to_payload(message) if result is True else result
                # Already acked: at-most-once delivery.
                yield TriggerEvent(payload)  # type: ignore[no-untyped-call]
                # One event per run: the sensor needs that, and the triggerer
                # restarts a watcher for the next message.
                return

    async def cleanup(self) -> None:
        """Close the connection opened by run()."""
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                await connection.close()
            except Exception:  # pylint: disable=broad-except
                self.log.warning(
                    "Failed to close the RabbitMQ connection", exc_info=True
                )
