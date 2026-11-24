"""Unit tests."""

import importlib
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Dict
from unittest import mock

import pytest
from airflow.exceptions import TaskDeferred
from pika.adapters.blocking_connection import BlockingChannel, BlockingConnection
from pika.spec import Basic, BasicProperties

from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor
from airflow.provider.rabbitmq.triggers.rabbitmq_trigger import RabbitMQTrigger

try:
    from airflow.sdk.bases.sensor import (  # Airflow 3.x
        BaseSensorOperator,
        PokeReturnValue,
    )
except ImportError:
    _sensor_base = importlib.import_module("airflow.sensors.base")  # Airflow 2.x
    BaseSensorOperator = _sensor_base.BaseSensorOperator
    PokeReturnValue = _sensor_base.PokeReturnValue


class TestRabbitMQSensor:
    """Tests for RabbitMQSensor"""

    conn_id = "rabbitmq_default"
    queue = "test_queue"
    task_id = "test_task_id"

    async def test_init(self):
        """Test sensor initialization"""
        # Test with default conn_id
        sensor1 = RabbitMQSensor(
            task_id=self.task_id,
            queue_name=self.queue,
        )

        assert sensor1.conn_id == self.conn_id
        assert sensor1.queue_name == self.queue
        assert sensor1.queue != self.queue  # still the executor queue
        assert sensor1.auto_ack is True
        assert isinstance(sensor1, BaseSensorOperator)

        # Test with conn_id
        sensor2 = RabbitMQSensor(
            task_id=self.task_id,
            conn_id="test_conn",
            queue_name=self.queue,
            auto_ack=False,
        )

        assert sensor2.conn_id == "test_conn"
        assert sensor2.auto_ack is False

    async def test_template_fields(self):
        """Test template fields"""
        assert "queue_name" in RabbitMQSensor.template_fields
        assert "queue" not in RabbitMQSensor.template_fields

    def test_executor_queue_is_separate_from_rabbitmq_queue(self) -> None:
        """queue sets the executor queue, queue_name the RabbitMQ queue"""
        sensor = RabbitMQSensor(
            task_id=self.task_id, queue_name=self.queue, queue="celery_queue"
        )

        assert sensor.queue_name == self.queue
        assert sensor.queue == "celery_queue"

    def test_dag_with_sensor_serializes(self) -> None:
        """Airflow can serialize a DAG using the sensor, as the DAG processor does"""
        serialized_objects = importlib.import_module(
            "airflow.serialization.serialized_objects"
        )
        if hasattr(serialized_objects, "DagSerialization"):  # Airflow 3.x
            dag_class = importlib.import_module("airflow.sdk").DAG
            serializer = serialized_objects.DagSerialization
        else:  # Airflow 2.x
            dag_class = importlib.import_module("airflow.models.dag").DAG
            serializer = serialized_objects.SerializedDAG

        with dag_class(dag_id="sensor_serialization", schedule=None) as dag:
            RabbitMQSensor(task_id=self.task_id, queue_name=self.queue)

        serialized = serializer.to_dict(dag)

        (task,) = serialized["dag"]["tasks"]
        task = task.get("__var", task)
        assert task["queue_name"] == self.queue

    @pytest.fixture
    def channel(self):
        """A channel whose basic_get returns whatever the test sets on it."""
        channel = mock.MagicMock(spec=BlockingChannel)
        connection = mock.MagicMock(spec=BlockingConnection)
        connection.channel.return_value = channel

        @contextmanager
        def connection_cm():
            yield connection

        with (
            mock.patch.object(RabbitMQHook, "__init__", return_value=None),
            mock.patch.object(
                RabbitMQHook, "get_sync_connection_cm", side_effect=connection_cm
            ),
        ):
            yield channel

    @staticmethod
    def _message(channel, body: bytes, **properties: Any) -> None:
        method = Basic.GetOk(
            delivery_tag=7, redelivered=False, exchange="orders", routing_key="new"
        )
        channel.basic_get.return_value = (method, BasicProperties(**properties), body)

    def test_poke_returns_message_via_xcom(self, channel) -> None:
        """A found message is pushed to XCom with its properties, and acked"""
        self._message(
            channel,
            b"test message",
            content_type="text/plain",
            message_id="m-1",
            correlation_id="c-1",
            headers={"attempt": 2},
        )
        sensor = RabbitMQSensor(task_id=self.task_id, queue_name=self.queue)

        result = sensor.poke({})

        assert isinstance(result, PokeReturnValue)
        assert result.is_done is True
        assert result.xcom_value == {
            "body": "test message",
            "body_encoding": "utf-8",
            "exchange": "orders",
            "routing_key": "new",
            "redelivered": False,
            "content_type": "text/plain",
            "message_id": "m-1",
            "correlation_id": "c-1",
            "headers": {"attempt": "2"},
        }
        channel.basic_get.assert_called_once_with(self.queue, auto_ack=False)
        channel.basic_ack.assert_called_once_with(7)
        channel.basic_nack.assert_not_called()

    def test_poke_base64_encodes_binary_body(self, channel) -> None:
        """A body that isn't UTF-8 is base64-encoded, so XCom can store it"""
        self._message(channel, b"\xff\xfe")
        sensor = RabbitMQSensor(task_id=self.task_id, queue_name=self.queue)

        result = sensor.poke({})

        assert result.xcom_value["body"] == "//4="
        assert result.xcom_value["body_encoding"] == "base64"

    def test_poke_deserializes_json(self, channel) -> None:
        """deserialize="json" parses the body"""
        self._message(channel, b'{"order_id": 42}')
        sensor = RabbitMQSensor(
            task_id=self.task_id, queue_name=self.queue, deserialize="json"
        )

        result = sensor.poke({})

        assert result.xcom_value["body"] == {"order_id": 42}
        assert result.xcom_value["body_encoding"] == "json"

    def test_poke_requeues_invalid_json(self, channel) -> None:
        """A body that isn't JSON fails the task and stays on the queue"""
        self._message(channel, b"not json")
        sensor = RabbitMQSensor(
            task_id=self.task_id, queue_name=self.queue, deserialize="json"
        )

        with pytest.raises(ValueError):
            sensor.poke({})

        channel.basic_nack.assert_called_once_with(7, requeue=True)
        channel.basic_ack.assert_not_called()

    def test_poke_requeues_message_over_max_xcom_bytes(self, channel) -> None:
        """A body over max_xcom_bytes fails the task and stays on the queue"""
        self._message(channel, b"12345")
        sensor = RabbitMQSensor(
            task_id=self.task_id, queue_name=self.queue, max_xcom_bytes=4
        )

        with pytest.raises(ValueError, match="max_xcom_bytes"):
            sensor.poke({})

        channel.basic_nack.assert_called_once_with(7, requeue=True)
        channel.basic_ack.assert_not_called()

    def test_poke_without_auto_ack_peeks(self, channel) -> None:
        """auto_ack=False returns the message and requeues it explicitly"""
        self._message(channel, b"test message")
        sensor = RabbitMQSensor(
            task_id=self.task_id, queue_name=self.queue, auto_ack=False
        )

        result = sensor.poke({})

        assert result.xcom_value["body"] == "test message"
        channel.basic_nack.assert_called_once_with(7, requeue=True)
        channel.basic_ack.assert_not_called()

    def test_poke_logs_body_at_debug_only(self, channel) -> None:
        """INFO logs the size and routing key, never the body"""
        self._message(channel, b"secret payload")
        sensor = RabbitMQSensor(task_id=self.task_id, queue_name=self.queue)

        with mock.patch.object(RabbitMQSensor, "log") as log:
            sensor.poke({})

        log.info.assert_called_once_with(
            "Received a %d-byte message with routing key %r", 14, "new"
        )
        log.debug.assert_called_once_with("Message body: %r", b"secret payload")

    def test_deferrable_execute_defers_to_trigger(self) -> None:
        """execute() defers to a passive trigger and keeps the sensor timeout"""
        sensor = RabbitMQSensor(
            task_id=self.task_id,
            queue_name=self.queue,
            conn_id="test_conn",
            deferrable=True,
            timeout=60,
        )

        with pytest.raises(TaskDeferred) as deferred:
            sensor.execute({})

        trigger = deferred.value.trigger
        assert isinstance(trigger, RabbitMQTrigger)
        assert trigger.queue_name == self.queue
        assert trigger.conn_id == "test_conn"
        assert trigger.passive is True
        assert deferred.value.method_name == "execute_complete"
        assert deferred.value.timeout == timedelta(seconds=60)

    def test_deferrable_execute_complete_returns_payload(self) -> None:
        """The event payload is the XCom value"""
        sensor = RabbitMQSensor(
            task_id=self.task_id, queue_name=self.queue, deferrable=True
        )
        payload = {"body": "hello", "body_encoding": "utf-8"}

        assert sensor.execute_complete({}, payload) == payload

    @pytest.mark.parametrize(
        "options",
        [{"auto_ack": False}, {"deserialize": "json"}, {"max_xcom_bytes": 10}],
    )
    def test_deferrable_rejects_options_the_trigger_cannot_honour(
        self, options: Dict[str, Any]
    ) -> None:
        """The trigger always acks and builds the payload itself"""
        with pytest.raises(ValueError, match="deferrable"):
            RabbitMQSensor(
                task_id=self.task_id,
                queue_name=self.queue,
                deferrable=True,
                **options,
            )

    def test_not_deferrable_polls(self, channel) -> None:
        """Without deferrable, execute() polls and never defers"""
        self._message(channel, b"polled")
        sensor = RabbitMQSensor(
            task_id=self.task_id, queue_name=self.queue, deferrable=False
        )

        assert sensor.execute({})["body"] == "polled"

    def test_init_rejects_unknown_deserialize(self) -> None:
        """An unknown deserialize value fails when the DAG is parsed"""
        with pytest.raises(ValueError, match="deserialize"):
            RabbitMQSensor(
                task_id=self.task_id, queue_name=self.queue, deserialize="yaml"
            )

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    @mock.patch.object(RabbitMQHook, "__init__")
    async def test_poke_without_message(
        self, mock_hook_init, mock_get_sync_connection_cm
    ):
        """Test poke method when no message is found"""
        # Setup mocks
        mock_hook_init.return_value = None
        mock_connection = mock.MagicMock(spec=BlockingConnection)
        mock_channel = mock.MagicMock(spec=BlockingChannel)

        mock_connection.channel.return_value = mock_channel
        mock_channel.basic_get.return_value = (None, None, None)

        # Setup context manager
        @contextmanager
        def mock_cm():
            yield mock_connection

        mock_get_sync_connection_cm.return_value = mock_cm()

        # Create sensor
        sensor = RabbitMQSensor(
            task_id=self.task_id,
            queue_name=self.queue,
            auto_ack=False,
        )

        # Call poke
        context: Dict[str, Any] = {}
        result = sensor.poke(context)

        # Assertions
        mock_hook_init.assert_called_once_with(conn_id=self.conn_id)
        mock_get_sync_connection_cm.assert_called_once()
        mock_connection.channel.assert_called_once()
        mock_channel.basic_get.assert_called_once_with(self.queue, auto_ack=False)
        assert result is False

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    @mock.patch.object(RabbitMQHook, "__init__")
    async def test_poke_with_exception(
        self, mock_hook_init, mock_get_sync_connection_cm
    ):
        """Test poke method when an exception occurs"""
        # Setup mocks
        mock_hook_init.return_value = None
        mock_get_sync_connection_cm.side_effect = ConnectionError("Test exception")

        # Create sensor
        sensor = RabbitMQSensor(
            task_id=self.task_id,
            queue_name=self.queue,
        )

        # Call poke
        context: Dict[str, Any] = {}
        result = sensor.poke(context)

        # Assertions
        mock_hook_init.assert_called_once_with(conn_id=self.conn_id)
        mock_get_sync_connection_cm.assert_called_once()
        assert result is False
