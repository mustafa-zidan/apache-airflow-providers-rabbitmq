import asyncio
from typing import Any, Dict
from unittest import mock

import pytest
from airflow.models import BaseOperator

from airflow.providers.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.providers.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)


class TestRabbitMQProducerOperator:
    """Tests for RabbitMQProducerOperator"""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up test fixtures"""
        self.connection_uri = "amqp://guest:guest@localhost:5672/"
        self.conn_id = "rabbitmq_default"
        self.message = "test message"
        self.exchange = "test_exchange"
        self.routing_key = "test_routing_key"
        self.task_id = "test_task_id"

    async def test_init(self):
        """Test operator initialization"""
        # Test with connection_uri
        operator1 = RabbitMQProducerOperator(
            task_id=self.task_id,
            connection_uri=self.connection_uri,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=False,
        )

        assert operator1.connection_uri == self.connection_uri
        assert operator1.conn_id == self.conn_id
        assert operator1.message == self.message
        assert operator1.exchange == self.exchange
        assert operator1.routing_key == self.routing_key
        assert operator1.use_async is False
        assert isinstance(operator1, BaseOperator)

        # Test with conn_id
        operator2 = RabbitMQProducerOperator(
            task_id=self.task_id,
            conn_id="test_conn",
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=False,
        )

        assert operator2.connection_uri is None
        assert operator2.conn_id == "test_conn"

    async def test_init_with_async(self):
        """Test operator initialization with async mode"""
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            connection_uri=self.connection_uri,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=True,
        )

        assert operator.use_async is True

    async def test_template_fields(self):
        """Test template fields"""
        assert "message" in RabbitMQProducerOperator.template_fields
        assert "exchange" in RabbitMQProducerOperator.template_fields
        assert "routing_key" in RabbitMQProducerOperator.template_fields

    @mock.patch.object(RabbitMQHook, "publish_sync")
    @mock.patch.object(RabbitMQHook, "__init__")
    async def test_execute_sync(self, mock_hook_init, mock_publish_sync):
        """Test execute method with synchronous mode"""
        # Setup mocks
        mock_hook_init.return_value = None

        # Create operator
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            connection_uri=self.connection_uri,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=False,
        )

        # Call execute
        context: Dict[str, Any] = {}
        operator.execute(context)

        # Assertions
        mock_hook_init.assert_called_once_with(
            connection_uri=self.connection_uri, conn_id=self.conn_id
        )
        mock_publish_sync.assert_called_once_with(
            self.message, self.exchange, self.routing_key
        )

    @mock.patch.object(asyncio, "run")
    @mock.patch.object(RabbitMQHook, "__init__")
    async def test_execute_async(self, mock_hook_init, mock_asyncio_run):
        """Test execute method with asynchronous mode"""
        # Setup mocks
        mock_hook_init.return_value = None

        # Create operator
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            connection_uri=self.connection_uri,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=True,
        )

        # Call execute
        context: Dict[str, Any] = {}
        operator.execute(context)

        # Assertions
        mock_hook_init.assert_called_once_with(
            connection_uri=self.connection_uri, conn_id=self.conn_id
        )
        mock_asyncio_run.assert_called_once()

    @mock.patch.object(RabbitMQHook, "publish_sync")
    @mock.patch.object(RabbitMQHook, "__init__")
    async def test_execute_with_error(self, mock_hook_init, mock_publish_sync):
        """Test execute method with error"""
        # Setup mocks
        mock_hook_init.return_value = None
        mock_publish_sync.side_effect = Exception("Test error")

        with mock.patch.object(
            RabbitMQHook, "publish_async", new_callable=mock.AsyncMock
        ):
            # Create operator
            operator = RabbitMQProducerOperator(
                task_id=self.task_id,
                connection_uri=self.connection_uri,
                message=self.message,
                exchange=self.exchange,
                routing_key=self.routing_key,
                use_async=False,
            )

            # Call execute
            context: Dict[str, Any] = {}
            with pytest.raises(Exception):
                operator.execute(context)

        # Assertions
        mock_hook_init.assert_called_once_with(
            connection_uri=self.connection_uri, conn_id=self.conn_id
        )
        mock_publish_sync.assert_called_once_with(
            self.message, self.exchange, self.routing_key
        )
