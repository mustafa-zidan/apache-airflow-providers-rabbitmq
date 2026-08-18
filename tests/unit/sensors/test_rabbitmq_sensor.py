from contextlib import contextmanager
from typing import Any, Dict
from unittest import mock

import pytest
from airflow.sensors.base import BaseSensorOperator
from pika.adapters.blocking_connection import BlockingChannel, BlockingConnection
from pika.frame import Method

from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor


class TestRabbitMQSensor:
    """Tests for RabbitMQSensor"""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up test fixtures"""
        self.connection_uri = "amqp://guest:guest@localhost:5672/"
        self.conn_id = "rabbitmq_default"
        self.queue = "test_queue"
        self.task_id = "test_task_id"

    async def test_init(self):
        """Test sensor initialization"""
        # Test with connection_uri
        sensor1 = RabbitMQSensor(
            task_id=self.task_id,
            connection_uri=self.connection_uri,
            queue=self.queue,
        )

        assert sensor1.connection_uri == self.connection_uri
        assert sensor1.conn_id == self.conn_id
        assert sensor1.queue == self.queue
        assert sensor1.auto_ack is True
        assert isinstance(sensor1, BaseSensorOperator)

        # Test with conn_id
        sensor2 = RabbitMQSensor(
            task_id=self.task_id,
            conn_id="test_conn",
            queue=self.queue,
            auto_ack=False,
        )

        assert sensor2.connection_uri is None
        assert sensor2.conn_id == "test_conn"
        assert sensor2.auto_ack is False

    async def test_template_fields(self):
        """Test template fields"""
        assert "queue" in RabbitMQSensor.template_fields

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    @mock.patch.object(RabbitMQHook, "__init__")
    async def test_poke_with_message(self, mock_hook_init, mock_get_sync_connection_cm):
        """Test poke method when a message is found"""
        # Setup mocks
        mock_hook_init.return_value = None
        mock_connection = mock.MagicMock(spec=BlockingConnection)
        mock_channel = mock.MagicMock(spec=BlockingChannel)
        mock_method_frame = mock.MagicMock(spec=Method)

        mock_connection.channel.return_value = mock_channel
        mock_channel.basic_get.return_value = (mock_method_frame, None, b"test message")

        # Setup context manager
        @contextmanager
        def mock_cm():
            yield mock_connection

        mock_get_sync_connection_cm.return_value = mock_cm()

        # Create sensor
        sensor = RabbitMQSensor(
            task_id=self.task_id,
            connection_uri=self.connection_uri,
            queue=self.queue,
            auto_ack=True,
        )

        # Call poke
        context: Dict[str, Any] = {}
        result = sensor.poke(context)

        # Assertions
        mock_hook_init.assert_called_once_with(
            connection_uri=self.connection_uri, conn_id=self.conn_id
        )
        mock_get_sync_connection_cm.assert_called_once()
        mock_connection.channel.assert_called_once()
        mock_channel.basic_get.assert_called_once_with(self.queue, auto_ack=True)
        assert result is True

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
            connection_uri=self.connection_uri,
            queue=self.queue,
            auto_ack=False,
        )

        # Call poke
        context: Dict[str, Any] = {}
        result = sensor.poke(context)

        # Assertions
        mock_hook_init.assert_called_once_with(
            connection_uri=self.connection_uri, conn_id=self.conn_id
        )
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
        mock_get_sync_connection_cm.side_effect = Exception("Test exception")

        # Create sensor
        sensor = RabbitMQSensor(
            task_id=self.task_id,
            connection_uri=self.connection_uri,
            queue=self.queue,
        )

        # Call poke
        context: Dict[str, Any] = {}
        result = sensor.poke(context)

        # Assertions
        mock_hook_init.assert_called_once_with(
            connection_uri=self.connection_uri, conn_id=self.conn_id
        )
        mock_get_sync_connection_cm.assert_called_once()
        assert result is False
