import asyncio
from typing import List, Optional
from unittest import mock

import pytest

from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.triggers.rabbitmq_trigger import RabbitMQTrigger

try:
    from airflow.sdk.definitions.connection import Connection
except ImportError:
    from airflow.models import Connection
try:
    from airflow.sdk.bases.hook import BaseHook
except ImportError:
    from airflow.hooks.base import BaseHook
try:
    from airflow.providers.common.compat.module_loading import import_string
except ImportError:
    from airflow.utils.module_loading import import_string

exchange_parametrize = pytest.mark.parametrize(
    "exchange_type,exchange_name,routing_key",
    [
        ("topic", "test_exchange", "test_routing_key"),
        (None, None, None),
    ],
)

requeue_parametrize = pytest.mark.parametrize("requeue_on_error", [True, False])


def accept_keep(message):
    return message.body == b"keep"


def transform_keep(prefix, message, suffix=""):
    if message.body != b"keep":
        return None
    return {"value": prefix + message.body.decode() + suffix}


class MockMessage:

    def __init__(self, body=b"Test_Message"):
        self.body = body
        # The attributes RabbitMQTrigger._to_payload reads.
        self.exchange = ""
        self.routing_key = "test_queue"
        self.content_type = None
        self.message_id = None
        self.correlation_id = None
        self.headers = {}

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
        with mock.patch.object(
            BaseHook, "get_connection", return_value=setup_connections
        ) as mock_base_conn:
            yield mock_base_conn

    @pytest.fixture()
    def mock_abstract_iterator(
        self, mock_async_rabbitmq_connection, mock_async_rabbitmq_channel
    ):
        mock_queue = mock.MagicMock()
        mock_message = MockMessage()
        mock_iter = MockQueueIterator([mock_message])
        mock_bind = mock.MagicMock()
        mock_queue.iterator = mock.MagicMock(return_value=mock_iter)
        mock_queue.bind = mock.AsyncMock(return_value=mock_bind)
        mock_exchange = mock.MagicMock()

        mock_async_rabbitmq_channel.set_qos = mock.AsyncMock()
        mock_async_rabbitmq_channel.declare_queue = mock.AsyncMock(
            return_value=mock_queue
        )
        mock_async_rabbitmq_channel.declare_exchange = mock.AsyncMock(
            return_value=mock_exchange
        )
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

        assert (
            classpath
            == "airflow.provider.rabbitmq.triggers.rabbitmq_trigger.RabbitMQTrigger"
        )
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

    def test_serialize_round_trip(self):
        """The triggerer can rebuild the trigger from what serialize() stores"""
        trigger = RabbitMQTrigger(
            queue_name="q",
            conn_id="c",
            exchange_name="ex",
            exchange_type="TOPIC",
            routing_key="a.#",
            durable=False,
            arguments_queue={"x-queue-type": "classic"},
        )
        classpath, kwargs = trigger.serialize()

        rebuilt = import_string(classpath)(**kwargs)

        assert rebuilt.serialize() == (classpath, kwargs)
        assert kwargs["exchange_type"] == "topic"

    def test_unknown_kwargs_are_ignored_with_a_warning(self):
        with mock.patch.object(
            RabbitMQTrigger, "log", new_callable=mock.PropertyMock
        ) as log:
            trigger = RabbitMQTrigger(queue_name="q", durabel=False, prefetch=5)

        log.return_value.warning.assert_called_once_with(
            "RabbitMQTrigger ignores unknown arguments: %s", "durabel, prefetch"
        )
        assert trigger.durable is True
        assert "durabel" not in trigger.serialize()[1]

    def test_known_kwargs_do_not_warn(self):
        with mock.patch.object(
            RabbitMQTrigger, "log", new_callable=mock.PropertyMock
        ) as log:
            trigger = RabbitMQTrigger(queue_name="q", durable=False, timeout=5)

        log.return_value.warning.assert_not_called()
        assert trigger.durable is False
        assert trigger.timeout == 5

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"exchange_type": "nope", "exchange_name": "ex"},
            {"exchange_type": "topic"},  # needs exchange_name
            {"exchange_name": "ex"},  # needs an exchange_type
            {"routing_key": "a.b"},  # needs an exchange
        ],
    )
    def test_invalid_exchange_arguments_raise(self, kwargs):
        with pytest.raises(ValueError):
            RabbitMQTrigger(queue_name="q", **kwargs)

    def test_routing_key_defaults_to_what_is_bound(self):
        trigger = RabbitMQTrigger(
            queue_name="q", exchange_type="topic", exchange_name="ex"
        )

        assert trigger.routing_key == "#"
        assert trigger.serialize()[1]["routing_key"] == "#"

    @exchange_parametrize
    @pytest.mark.asyncio
    async def test_run_yields_message_payload(
        self, mock_abstract_iterator, exchange_type, exchange_name, routing_key
    ):
        trigger = RabbitMQTrigger(
            queue_name=self.queue_name,
            conn_id=self.conn_id,
            exchange_type=exchange_type,
            exchange_name=exchange_name,
            routing_key=routing_key,
        )

        event = await asyncio.wait_for(trigger.run().__anext__(), timeout=1)

        assert event.payload["body"] == "Test_Message"
        assert event.payload["body_encoding"] == "utf-8"
        assert event.payload["routing_key"] == "test_queue"

    @pytest.mark.asyncio
    async def test_run_base64_encodes_binary_body(self, mock_abstract_iterator):
        mock_abstract_iterator.messages[0].body = b"\xff\xfe"
        trigger = RabbitMQTrigger(queue_name=self.queue_name, conn_id=self.conn_id)

        event = await asyncio.wait_for(trigger.run().__anext__(), timeout=1)

        assert event.payload["body"] == "//4="
        assert event.payload["body_encoding"] == "base64"

    @pytest.mark.asyncio
    async def test_run_skips_rejected_messages_without_waiting(
        self, mock_abstract_iterator
    ):
        mock_abstract_iterator.messages[:] = [
            MockMessage(b"skip"),
            MockMessage(b"keep"),
        ]
        trigger = RabbitMQTrigger(
            queue_name=self.queue_name,
            conn_id=self.conn_id,
            apply_function=f"{__name__}.accept_keep",
        )

        event = await asyncio.wait_for(trigger.run().__anext__(), timeout=1)

        assert event.payload["body"] == "keep"

    @pytest.mark.asyncio
    async def test_run_yields_apply_function_return_value(self, mock_abstract_iterator):
        mock_abstract_iterator.messages[:] = [
            MockMessage(b"skip"),
            MockMessage(b"keep"),
        ]
        trigger = RabbitMQTrigger(
            queue_name=self.queue_name,
            conn_id=self.conn_id,
            apply_function=f"{__name__}.transform_keep",
            apply_function_args=["<"],
            apply_function_kwargs={"suffix": ">"},
        )

        event = await asyncio.wait_for(trigger.run().__anext__(), timeout=1)

        assert event.payload == {"value": "<keep>"}

    @pytest.mark.parametrize(
        "type_key,var_key",
        [("__type", "__var"), ("Encoding.TYPE", "Encoding.VAR")],
    )
    def test_unwraps_serialized_kwargs(self, type_key, var_key):
        """Airflow < 3.3.1 can pass AssetWatcher kwargs still wrapped (#28)"""

        def wrap(type_, var):
            return {var_key: var, type_key: type_}

        trigger = RabbitMQTrigger(
            queue_name="q",
            exchange_type="topic",
            exchange_name="ex",
            apply_function_args=wrap("tuple", [1, 2]),
            apply_function_kwargs=wrap("dict", {"one": 1}),
            arguments_queue=wrap(
                "dict",
                {
                    "x-queue-type": "classic",
                    "x-message-ttl": 604800,
                    "x-nested": wrap("dict", {"a": 1}),
                },
            ),
            arguments_exchange=wrap("dict", {"alternate-exchange": "alt"}),
            arguments_bind=wrap("dict", {"x-match": "all"}),
        )

        kwargs = trigger.serialize()[1]
        assert kwargs["arguments_queue"] == {
            "x-queue-type": "classic",
            "x-message-ttl": 604800,
            "x-nested": {"a": 1},
        }
        assert kwargs["arguments_exchange"] == {"alternate-exchange": "alt"}
        assert kwargs["arguments_bind"] == {"x-match": "all"}
        assert kwargs["apply_function_args"] == [1, 2]
        assert kwargs["apply_function_kwargs"] == {"one": 1}

    def test_plain_kwargs_with_marker_like_keys_are_kept(self):
        arguments = {"__type": "user-value", "x-queue-type": "classic"}

        trigger = RabbitMQTrigger(queue_name="q", arguments_queue=arguments)

        assert trigger.arguments_queue == arguments

    @requeue_parametrize
    @pytest.mark.asyncio
    async def test_run_processes_with_requeue_setting(
        self, mock_abstract_iterator, requeue_on_error
    ):
        trigger = RabbitMQTrigger(
            conn_id=self.conn_id,
            queue_name=self.queue_name,
            requeue_on_error=requeue_on_error,
        )
        mock_message = mock_abstract_iterator.messages[0]

        await asyncio.wait_for(trigger.run().__anext__(), timeout=1)

        mock_message.process.assert_called_once_with(
            requeue=requeue_on_error, reject_on_redelivered=True
        )

    @pytest.mark.asyncio
    async def test_run_declares_queue_only_without_exchange(
        self, mock_abstract_iterator, mock_async_rabbitmq_channel
    ):
        trigger = RabbitMQTrigger(
            queue_name=self.queue_name, conn_id=self.conn_id, passive=True
        )

        await asyncio.wait_for(trigger.run().__anext__(), timeout=1)

        mock_async_rabbitmq_channel.declare_queue.assert_awaited_once_with(
            name=self.queue_name,
            durable=True,
            exclusive=False,
            passive=True,
            auto_delete=False,
            arguments=None,
            timeout=None,
        )
        mock_async_rabbitmq_channel.declare_exchange.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_declares_and_binds_the_exchange(
        self, mock_abstract_iterator, mock_async_rabbitmq_channel
    ):
        trigger = RabbitMQTrigger(
            queue_name=self.queue_name,
            conn_id=self.conn_id,
            exchange_name=self.exchange_name,
            exchange_type=self.exchange_type,
            routing_key="a.#",
            arguments_bind={"x-match": "all"},
        )

        await asyncio.wait_for(trigger.run().__anext__(), timeout=1)

        channel = mock_async_rabbitmq_channel
        channel.declare_exchange.assert_awaited_once_with(
            name=self.exchange_name,
            type="topic",
            durable=True,
            auto_delete=False,
            internal=False,
            passive=False,
            arguments=None,
            timeout=None,
        )
        channel.declare_queue.return_value.bind.assert_awaited_once_with(
            exchange=channel.declare_exchange.return_value,
            routing_key="a.#",
            arguments={"x-match": "all"},
            timeout=None,
        )

    @pytest.mark.asyncio
    async def test_connection_failure_retries_without_logging_the_uri(self):
        trigger = RabbitMQTrigger(queue_name="q", poll_interval=0)
        connection = mock.AsyncMock()
        with (
            mock.patch.object(
                RabbitMQHook,
                "get_async_connection",
                side_effect=[ConnectionError("amqp://u:secret@h"), connection],
            ),
            mock.patch.object(
                type(trigger), "log", new_callable=mock.PropertyMock
            ) as log,
        ):
            assert await trigger._connect() is connection

        logged = str(log.return_value.mock_calls)
        assert "secret" not in logged
        assert "ConnectionError" in logged

    @pytest.mark.asyncio
    async def test_cleanup_close_connection(
        self, mock_abstract_iterator, mock_async_rabbitmq_connection
    ):
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
