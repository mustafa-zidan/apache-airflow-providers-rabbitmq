"""Sensor that waits for messages in a RabbitMQ queue."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional, Sequence, cast

from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPError
from pika.spec import Basic, BasicProperties

from airflow.provider.rabbitmq._compat import BaseSensorOperator, PokeReturnValue
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.messages.incoming import (
    check_deserialize,
    message_payload,
)
from airflow.provider.rabbitmq.triggers.rabbitmq_trigger import RabbitMQTrigger

if TYPE_CHECKING:
    from airflow.provider.rabbitmq._compat import Context


class RabbitMQSensor(BaseSensorOperator):  # pylint: disable=too-many-ancestors
    """
    Airflow Sensor to wait for messages in a RabbitMQ queue.

    This sensor periodically checks a specified RabbitMQ queue. When it gets a
    message it succeeds and pushes the message to XCom as the dict
    ``message_payload`` builds: ``body``, ``body_encoding``, ``exchange``,
    ``routing_key``, ``redelivered``, ``content_type``, ``message_id``,
    ``correlation_id`` and ``headers``.

    The XCom value is stored in the Airflow metadata database, so set
    ``max_xcom_bytes`` when the queue can carry large messages.

    :param queue_name: The name of the RabbitMQ queue to monitor.
    :param conn_id: The Airflow connection id to use. Default is "rabbitmq_default".
    :param auto_ack: Acknowledge the message, removing it from the queue. Default is
        True. With False the sensor peeks: it returns the message and requeues it.
    :param deserialize: None to return the body as a string (base64 when it isn't
        UTF-8), or "json" to parse it. A body that fails to parse fails the task and
        stays on the queue.
    :param max_xcom_bytes: Fail the task, leaving the message on the queue, when the
        body is larger than this. Default None, no limit.
    :param deferrable: Wait in the triggerer instead of polling, so the task holds no
        worker slot. Default is False. The trigger acks
        the message before the task resumes, so delivery is at-most-once: if the
        triggerer dies before the event is stored, or the resumed task fails, the
        message is lost. It needs ``auto_ack=True`` and can't be combined with
        ``deserialize`` or ``max_xcom_bytes``. ``timeout`` still applies while
        deferred; ``mode``, ``poke_interval`` and ``soft_fail`` don't.

    ``queue`` is not the RabbitMQ queue: like on every operator, it is the executor
    queue the task runs on.
    """

    template_fields: Sequence[str] = ("queue_name",)
    ui_color = "#f0ede4"

    def __init__(
        self,
        queue_name: str,
        conn_id: str = "rabbitmq_default",
        auto_ack: bool = True,
        deserialize: Optional[str] = None,
        max_xcom_bytes: Optional[int] = None,
        deferrable: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the RabbitMQSensor.

        :param queue_name: The name of the RabbitMQ queue to monitor.
        :param conn_id: The Airflow connection id to use. Default is "rabbitmq_default".
        :param auto_ack: Acknowledge the message, or requeue it if False. Default is True.
        :param deserialize: None, or "json" to parse the body.
        :param max_xcom_bytes: Largest body to push to XCom. Default None, no limit.
        :param deferrable: Wait in the triggerer instead of polling.
        """
        super().__init__(**kwargs)
        check_deserialize(deserialize)
        if deferrable and (not auto_ack or deserialize or max_xcom_bytes is not None):
            raise ValueError(
                "deferrable=True can't be combined with auto_ack=False, deserialize "
                "or max_xcom_bytes: the trigger always acks and builds the payload"
            )
        self.conn_id: str = conn_id
        self.queue_name: str = queue_name
        self.auto_ack: bool = auto_ack
        self.deserialize: Optional[str] = deserialize
        self.max_xcom_bytes: Optional[int] = max_xcom_bytes
        self.deferrable: bool = deferrable

    def execute(self, context: Context) -> Any:
        """Poll, or defer to a RabbitMQTrigger when ``deferrable`` is set."""
        if self.deferrable:
            self.defer(
                trigger=RabbitMQTrigger(
                    queue_name=self.queue_name, conn_id=self.conn_id, passive=True
                ),
                method_name="execute_complete",
                timeout=timedelta(seconds=self.timeout),
            )
        return super().execute(context)

    def execute_complete(
        self, context: Context, event: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the trigger's payload, the same dict a poked sensor pushes to XCom."""
        return event

    def poke(self, _context: Context) -> bool | PokeReturnValue:
        """
        Checks the RabbitMQ queue for new messages.

        :param _context: Airflow's execution context dictionary (unused).
        :return: A PokeReturnValue carrying the message if one is found; otherwise,
            False.
        """
        hook = RabbitMQHook(conn_id=self.conn_id)
        try:
            with hook.get_sync_connection_cm() as conn:
                channel: BlockingChannel = conn.channel()

                # Always ack manually, so a message that fails to become a payload
                # goes back on the queue instead of being lost.
                method_frame: Optional[Basic.GetOk]
                method_frame, properties, body = channel.basic_get(
                    self.queue_name, auto_ack=False
                )
                if not method_frame:
                    return False
                # A GetOk always has properties and a delivery tag; an empty body
                # comes back as None.
                properties = cast(BasicProperties, properties)
                delivery_tag = cast(int, method_frame.delivery_tag)
                body = body or b""

                try:
                    payload = self._to_payload(method_frame, properties, body)
                except Exception:
                    channel.basic_nack(delivery_tag, requeue=True)
                    raise

                # Payloads can be large or hold personal data: body at DEBUG only.
                self.log.info(
                    "Received a %d-byte message with routing key %r",
                    len(body),
                    method_frame.routing_key,
                )
                self.log.debug("Message body: %r", body)

                if self.auto_ack:
                    channel.basic_ack(delivery_tag)
                else:
                    channel.basic_nack(delivery_tag, requeue=True)
                return PokeReturnValue(is_done=True, xcom_value=payload)

        except (ConnectionError, AMQPError) as e:
            self.log.error("Error during RabbitMQ poke: %s", e)

        return False

    def _to_payload(
        self, method_frame: Basic.GetOk, properties: BasicProperties, body: bytes
    ) -> dict[str, Any]:
        """Check the body size and build the XCom payload."""
        if self.max_xcom_bytes is not None and len(body) > self.max_xcom_bytes:
            raise ValueError(
                f"Message is {len(body)} bytes, over max_xcom_bytes "
                f"({self.max_xcom_bytes}); it was left on the queue"
            )
        return message_payload(
            body,
            exchange=_text(method_frame.exchange),
            routing_key=_text(method_frame.routing_key),
            redelivered=method_frame.redelivered,
            content_type=_text(properties.content_type),
            message_id=_text(properties.message_id),
            correlation_id=_text(properties.correlation_id),
            headers=properties.headers,
            deserialize=self.deserialize,
        )


def _text(value: str | bytes | None) -> Optional[str]:
    """pika returns a short string as bytes when it isn't valid UTF-8."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value
