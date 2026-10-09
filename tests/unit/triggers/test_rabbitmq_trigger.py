import asyncio
import pytest
from unittest import mock
from typing import Any, List, Optional
from airflow.provider.rabbitmq.triggers.rabbitmq_trigger import RabbitMQTrigger

try:
    from airflow.sdk.definitions.connection import Connection
except ImportError:
    from airflow.models import Connection
try:
    from airflow.sdk.bases.hook import BaseHook
except ImportError:
    from airflow.hooks.base import BaseHook

exchange_parametrize = pytest.mark.parametrize(
    "exchange_type,exchange_name,routing_key",
    [
        ("topic", "test_exchange", "test_routing_key"),
        (None, None, None),
    ]
)

requeue_parametrize = pytest.mark.parametrize("requeue_on_error", [True, False])

def apply_function_true(message):
    return True

def apply_function_false(message):
    return False

class MockMessage:

    def __init__(self, body=b"Test_Message"):
        self.body = body

        self.mock_context = mock.AsyncMock()
        self.mock_context.__aenter__.return_value = self
        self.mock_context.__aexit__.return_value = None

        self.process = mock.MagicMock(return_value=self.mock_context)


class MockQueueIterator:
    def __init__(self, messages: Optional[List[MockMessage]] = None):
        self.messages = messages if messages is not None else [MockMessage()]
        self._index = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self) -> MockMessage:
        if self._index < len(self.messages):
            message = self.messages[self._index]
            self._index += 1
            return message
        raise StopAsyncIteration


class TestRabbitMQTrigger:
    """Unit tests for the RabbitMQTrigger class"""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.conn_id = "rabbitmq"
        self.queue_name = "test_queue"
        self.exchange_type = "topic"
        self.exchange_name = "test_exchange"

    @pytest.fixture()
    def setup_connections(self):
        return Connection(
            conn_id="rabbitmq",
            conn_type="rabbitmq",
            host="localhost",
            port=5672,
            login="guest",
            password="123",
            schema="/default",
        )

    @pytest.fixture(autouse=True)
    def mock_base_get_connection(self, setup_connections):
        with mock.patch.object(BaseHook, "get_connection", return_value=setup_connections) as mock_base_conn:
            yield mock_base_conn

    @pytest.fixture()
    def mock_abstract_iterator(self,
                               mock_async_rabbitmq_connection,
                               mock_async_rabbitmq_channel):
        mock_queue = mock.MagicMock()
        mock_message = MockMessage()
        mock_iter = MockQueueIterator([mock_message])
        mock_bind = mock.MagicMock()
        mock_queue.iterator = mock.MagicMock(return_value=mock_iter)
        mock_queue.bind = mock.AsyncMock(return_value=mock_bind)
        mock_exchange = mock.MagicMock()

        mock_async_rabbitmq_channel.set_qos = mock.AsyncMock()
        mock_async_rabbitmq_channel.declare_queue = mock.AsyncMock(return_value=mock_queue)
        mock_async_rabbitmq_channel.declare_exchange = mock.AsyncMock(return_value=mock_exchange)
        mock_async_rabbitmq_connection.return_value.channel = mock.AsyncMock(
            return_value=mock_async_rabbitmq_channel
        )
        return mock_iter

    def test_initializes(self):
        trigger = RabbitMQTrigger(
            conn_id=self.conn_id,
            queue_name=self.queue_name,
        )

        if hasattr(trigger, "_task_instance"):
            assert trigger.task_instance is None
            assert trigger._task_instance is None
        else:
            assert trigger.task_instance is None

    def test_serialization(self):
        """Test serialization of RabbitMQ connection"""
        trigger = RabbitMQTrigger(
            conn_id=self.conn_id,
            queue_name=self.queue_name,
            exchange_type=self.exchange_type,
            exchange_name=self.exchange_name,
            routing_key="test_routing_key",
            requeue_on_error=True,
            poll_interval=10,
            apply_function="test.function",
            apply_function_args=[1, 2],
            apply_function_kwargs=dict(one=1, two=2),
            durable=False,
            exclusive=False,
            passive=False,
            auto_delete=False,
            internal=False,
            timeout=10,
            arguments_queue={"x-test-argument": "test-value"},
            arguments_exchange={"x-test-argument": "test-value"},
            arguments_bind={"x-test-argument": "test-value"},
        )

        assert isinstance(trigger, RabbitMQTrigger)

        classpath, kwargs = trigger.serialize()

        assert classpath == "airflow.provider.rabbitmq.triggers.rabbitmq_trigger.RabbitMQTrigger"
        assert kwargs == dict(
            queue_name="test_queue",
            conn_id="rabbitmq",
            exchange_type="topic",
            exchange_name="test_exchange",
            routing_key="test_routing_key",
            requeue_on_error=True,
            poll_interval=10,
            apply_function="test.function",
            apply_function_args=[1, 2],
            apply_function_kwargs={"one": 1, "two": 2},
            durable=False,
            exclusive=False,
            passive=False,
            auto_delete=False,
            internal=False,
            timeout=10,
            arguments_queue={"x-test-argument": "test-value"},
            arguments_exchange={"x-test-argument": "test-value"},
            arguments_bind={"x-test-argument": "test-value"},
        )

    @exchange_parametrize
    @pytest.mark.parametrize(
        "apply_function",
        [
            "tests.unit.triggers.test_rabbitmq_trigger.apply_function_true",
            None
        ]
    )
    @pytest.mark.asyncio
    async def test_trigger_run_good(self,
                                    mock_abstract_iterator,
                                    apply_function,
                                    exchange_type,
                                    exchange_name,
                                    routing_key):
        trigger = RabbitMQTrigger(
            conn_id=self.conn_id,
            queue_name=self.queue_name,
            apply_function=apply_function,
            exchange_type = exchange_type,
            exchange_name = exchange_name,
            routing_key = routing_key
        )
        task = asyncio.create_task(trigger.run().__anext__())
        await asyncio.sleep(1)
        assert task.done() is True
        asyncio.get_event_loop().stop()

    @exchange_parametrize
    @pytest.mark.asyncio
    async def test_trigger_run_bad(self,
                                   mock_abstract_iterator,
                                   exchange_type,
                                   exchange_name,
                                   routing_key):
        trigger = RabbitMQTrigger(
            conn_id=self.conn_id,
            queue_name=self.queue_name,
            apply_function="tests.unit.triggers.test_rabbitmq_trigger.apply_function_false",
            exchange_type=exchange_type,
            exchange_name=exchange_name,
            routing_key=routing_key
        )
        task = asyncio.create_task(trigger.run().__anext__())
        await asyncio.sleep(1)
        assert task.done() is False
        task.cancel()

    @requeue_parametrize
    @pytest.mark.asyncio
    async def test_trigger_run_process_message(self, mock_abstract_iterator, requeue_on_error):
        trigger = RabbitMQTrigger(conn_id=self.conn_id, queue_name=self.queue_name, requeue_on_error=requeue_on_error)
        mock_message = mock_abstract_iterator.messages[0]

        task = asyncio.create_task(trigger.run().__anext__())
        await asyncio.sleep(1)
        try:
            assert task.done() is True
            mock_message.process.assert_called_once_with(requeue=requeue_on_error)
        finally:
            task.cancel()

    @pytest.mark.asyncio
    async def test_cleanup_close_connection(self, mock_abstract_iterator, mock_async_rabbitmq_connection):
        mock_conn_instance = mock_async_rabbitmq_connection.return_value
        mock_conn_instance.close = mock.AsyncMock()

        trigger = RabbitMQTrigger(
            conn_id=self.conn_id,
            queue_name=self.queue_name,
        )

        generator = trigger.run()
        await generator.__anext__()
        await trigger.cleanup()
        await generator.aclose()

        mock_conn_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_does_not_raise_without_connection(self):
        trigger = RabbitMQTrigger(conn_id=self.conn_id, queue_name=self.queue_name)
        await trigger.cleanup()
