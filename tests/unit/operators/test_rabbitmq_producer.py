"""Unit tests."""

import asyncio
from types import MappingProxyType
from typing import Any, Dict
from unittest import mock

import pytest
from airflow.models import BaseOperator

from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)


class TestRabbitMQProducerOperator:
    """Tests for RabbitMQProducerOperator"""

    conn_id = "rabbitmq_default"
    message = "test message"
    exchange = "test_exchange"
    routing_key = "test_routing_key"
    task_id = "test_task_id"
    delivery = {"confirm": True, "mandatory": False}

    async def test_init(self):
        """Test operator initialization"""
        # Test with default conn_id
        operator1 = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=False,
        )

        assert operator1.conn_id == self.conn_id
        assert operator1.message == self.message
        assert operator1.exchange == self.exchange
        assert operator1.routing_key == self.routing_key
        assert operator1.use_async is False
        assert operator1.confirm is True
        assert operator1.mandatory is False
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

        assert operator2.conn_id == "test_conn"

    async def test_init_with_async(self):
        """Test operator initialization with async mode"""
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
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
        assert "properties" in RabbitMQProducerOperator.template_fields

    def test_init_rejects_unknown_properties(self):
        with pytest.raises(ValueError, match="Unknown message properties: persistent"):
            RabbitMQProducerOperator(
                task_id=self.task_id,
                message=self.message,
                exchange=self.exchange,
                routing_key=self.routing_key,
                properties={"persistent": True},
            )

    @pytest.mark.parametrize(
        "item",
        [
            {"body": "b", "properties": {"persistent": True}},
            MappingProxyType({"body": "b", "properties": {"persistent": True}}),
        ],
    )
    def test_init_rejects_unknown_batch_item_properties(self, item):
        with pytest.raises(ValueError, match="Unknown message properties: persistent"):
            RabbitMQProducerOperator(
                task_id=self.task_id,
                message=["ok", item],
                exchange=self.exchange,
                routing_key=self.routing_key,
            )

    def test_init_rejects_batch_item_without_body(self):
        with pytest.raises(ValueError, match="must contain 'body' or 'message'"):
            RabbitMQProducerOperator(
                task_id=self.task_id,
                message=[{"routing_key": "rk"}],
                exchange=self.exchange,
                routing_key=self.routing_key,
            )

    def test_init_accepts_templated_property_values(self):
        """Values are validated after rendering, so templates pass __init__"""
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            properties={"priority": "{{ params.priority }}"},
        )

        assert operator.properties == {"priority": "{{ params.priority }}"}

    @mock.patch.object(RabbitMQHook, "publish_sync")
    @mock.patch.object(RabbitMQHook, "__init__", return_value=None)
    def test_execute_passes_properties(self, _, mock_publish_sync):
        properties = {"delivery_mode": 2, "headers": {"source": "airflow"}}
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=b"binary",
            exchange=self.exchange,
            routing_key=self.routing_key,
            properties=properties,
        )

        operator.execute({})

        mock_publish_sync.assert_called_once_with(
            b"binary",
            self.exchange,
            self.routing_key,
            properties=properties,
            **self.delivery,
        )

    @mock.patch.object(RabbitMQHook, "publish_sync")
    @mock.patch.object(RabbitMQHook, "__init__")
    async def test_execute_sync(self, mock_hook_init, mock_publish_sync):
        """Test execute method with synchronous mode"""
        # Setup mocks
        mock_hook_init.return_value = None

        # Create operator
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=False,
        )

        # Call execute
        context: Dict[str, Any] = {}
        operator.execute(context)

        # Assertions
        mock_hook_init.assert_called_once_with(conn_id=self.conn_id)
        mock_publish_sync.assert_called_once_with(
            self.message,
            self.exchange,
            self.routing_key,
            properties=None,
            **self.delivery,
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
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=True,
        )

        # Call execute
        context: Dict[str, Any] = {}
        operator.execute(context)

        # Assertions
        mock_hook_init.assert_called_once_with(conn_id=self.conn_id)
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
        mock_hook_init.assert_called_once_with(conn_id=self.conn_id)
        mock_publish_sync.assert_called_once_with(
            self.message,
            self.exchange,
            self.routing_key,
            properties=None,
            **self.delivery,
        )

    @mock.patch.object(RabbitMQHook, "publish_batch_sync", return_value=2)
    @mock.patch.object(RabbitMQHook, "__init__", return_value=None)
    def test_execute_batch_sync(self, _, mock_publish_batch_sync):
        """A list message is published as one batch and the count is returned"""
        messages = ["a", {"body": "b", "routing_key": "other"}]
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=messages,
            exchange=self.exchange,
            routing_key=self.routing_key,
            properties={"delivery_mode": 2},
        )

        assert operator.execute({}) == 2
        mock_publish_batch_sync.assert_called_once_with(
            messages,
            self.exchange,
            self.routing_key,
            properties={"delivery_mode": 2},
            **self.delivery,
        )

    @mock.patch.object(RabbitMQHook, "publish_batch_async", new_callable=mock.AsyncMock)
    @mock.patch.object(RabbitMQHook, "__init__", return_value=None)
    def test_execute_batch_async(self, _, mock_publish_batch_async):
        mock_publish_batch_async.return_value = 3
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=("a", "b", "c"),
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=True,
        )

        assert operator.execute({}) == 3
        mock_publish_batch_async.assert_awaited_once_with(
            ("a", "b", "c"),
            self.exchange,
            self.routing_key,
            properties=None,
            **self.delivery,
        )

    @pytest.mark.parametrize("use_async", [False, True])
    def test_execute_passes_delivery_options(self, use_async: bool) -> None:
        """confirm and mandatory reach the hook on both paths"""
        method = "publish_async" if use_async else "publish_sync"
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
            use_async=use_async,
            mandatory=True,
        )

        with (
            mock.patch.object(RabbitMQHook, "__init__", return_value=None),
            mock.patch.object(
                RabbitMQHook,
                method,
                new_callable=mock.AsyncMock if use_async else mock.MagicMock,
            ) as publish,
        ):
            operator.execute({})

        assert publish.call_args.kwargs["confirm"] is True
        assert publish.call_args.kwargs["mandatory"] is True

    def test_init_rejects_mandatory_without_confirm(self):
        """mandatory can't be honoured without confirms, so the DAG fails to parse"""
        with pytest.raises(ValueError, match="mandatory=True requires confirm=True"):
            RabbitMQProducerOperator(
                task_id=self.task_id,
                message=self.message,
                exchange=self.exchange,
                routing_key=self.routing_key,
                confirm=False,
                mandatory=True,
            )

    @mock.patch.object(RabbitMQHook, "publish_batch_sync")
    @mock.patch.object(RabbitMQHook, "__init__", return_value=None)
    def test_execute_empty_batch_publishes_nothing(self, _, mock_publish_batch_sync):
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=[],
            exchange=self.exchange,
            routing_key=self.routing_key,
        )

        assert operator.execute({}) == 0
        mock_publish_batch_sync.assert_not_called()

    @mock.patch.object(RabbitMQHook, "publish_sync")
    @mock.patch.object(RabbitMQHook, "__init__", return_value=None)
    def test_execute_single_message_returns_one(self, _, mock_publish_sync):
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
        )

        assert operator.execute({}) == 1

    @mock.patch.object(RabbitMQHook, "__init__", return_value=None)
    def test_execute_rejects_unsupported_message_type(self, _):
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            message=self.message,
            exchange=self.exchange,
            routing_key=self.routing_key,
        )
        operator.message = 42  # e.g. a template that rendered to a native int

        with pytest.raises(TypeError, match="got int"):
            operator.execute({})
