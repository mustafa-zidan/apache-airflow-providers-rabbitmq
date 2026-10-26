"""Unit tests."""

import ssl
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock

import aio_pika
import aiormq
import pika
import pytest
from pika.adapters.blocking_connection import BlockingConnection, ReturnedMessage

from airflow.provider.rabbitmq.exceptions import MessageNotDeliveredError
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import (
    RabbitMQHook,
    build_aio_pika_message,
    build_pika_properties,
)
from airflow.provider.rabbitmq.messages.properties import normalize_properties

ALL_PROPERTIES = {
    "content_type": "application/json",
    "content_encoding": "utf-8",
    "headers": {"source": "airflow"},
    "delivery_mode": 2,
    "priority": 5,
    "correlation_id": "run-1",
    "reply_to": "replies",
    "expiration": "60000",
    "message_id": "m-1",
    "timestamp": 1700000000,
    "type": "order.created",
    "user_id": "guest",
    "app_id": "airflow",
}


class TestRabbitMQHook:
    """Tests for RabbitMQHook"""

    connection_uri = "amqp://guest:guest@localhost:5672/"
    conn_id = "rabbitmq_default"

    @property
    def hook(self) -> RabbitMQHook:
        """A hook configured with the test connection URI"""
        return RabbitMQHook(connection_uri=self.connection_uri)

    def _hook(self, **delivery: bool) -> RabbitMQHook:
        """A hook with the test connection URI and the given confirm/mandatory"""
        return RabbitMQHook(connection_uri=self.connection_uri, **delivery)

    async def test_init(self):
        """Test hook initialization"""
        # Test with connection_uri
        hook1 = RabbitMQHook(connection_uri=self.connection_uri)
        assert hook1.connection_uri == self.connection_uri
        assert hook1.conn_id == "rabbitmq_default"

        # Test with conn_id
        hook2 = RabbitMQHook(conn_id="test_conn")
        assert hook2.conn_id == "test_conn"

    @mock.patch("airflow.provider.rabbitmq.hooks.rabbitmq_hook.BaseHook.get_connection")
    async def test_connection_uri_property(self, mock_get_connection):
        """Test connection_uri property"""
        # Test with connection_uri provided
        hook1 = RabbitMQHook(connection_uri=self.connection_uri)
        assert hook1.connection_uri == self.connection_uri
        mock_get_connection.assert_not_called()

        # Test with host/port/login/password
        mock_conn = mock.MagicMock()
        mock_conn.host = "localhost"
        mock_conn.port = 5672
        mock_conn.login = "guest"
        mock_conn.password = "guest"
        mock_conn.schema = "vhost"
        mock_conn.extra_dejson = {}
        mock_get_connection.return_value = mock_conn

        hook2 = RabbitMQHook(conn_id="test_conn")
        assert hook2.connection_uri == "amqp://guest:guest@localhost:5672/vhost"
        mock_get_connection.assert_called_once_with("test_conn")

        # Test with connection_uri in extra
        mock_conn = mock.MagicMock()
        mock_conn.host = None
        mock_conn.port = None
        mock_conn.extra_dejson = {"connection_uri": self.connection_uri}
        mock_get_connection.return_value = mock_conn

        hook3 = RabbitMQHook(conn_id="test_conn2")
        assert hook3.connection_uri == self.connection_uri

    @pytest.mark.parametrize(
        ("login", "password", "schema", "expected_vhost"),
        [
            ("guest", "p@ss", None, "/"),
            ("guest", "a/b#c?d", None, "/"),
            ("us@er", "p:ss", None, "/"),
            ("guest", "guest", "/", "/"),
            ("guest", "guest", "team/prod", "team/prod"),
            ("guest", "", None, "/"),
            ("guest", None, None, "/"),
        ],
    )
    @mock.patch("airflow.provider.rabbitmq.hooks.rabbitmq_hook.BaseHook.get_connection")
    async def test_connection_uri_is_encoded(
        self,
        mock_get_connection: mock.MagicMock,
        login: str,
        password: str | None,
        schema: str | None,
        expected_vhost: str,
    ) -> None:
        """pika and aio-pika read back the connection fields unchanged"""
        mock_get_connection.return_value = mock.MagicMock(
            host="rabbitmq",
            port=5672,
            login=login,
            password=password,
            schema=schema,
            extra_dejson={},
        )

        uri = RabbitMQHook(conn_id="test_conn").connection_uri

        params = pika.URLParameters(uri)
        assert params.host == "rabbitmq"
        assert params.credentials.username == login
        assert params.credentials.password == (password or "")
        assert params.virtual_host == expected_vhost

        async_conn = aiormq.Connection(uri)
        assert async_conn.url.host == "rabbitmq"
        assert async_conn.url.user == login
        assert (async_conn.url.password or "") == (password or "")
        assert async_conn.vhost == expected_vhost

    @mock.patch("pika.BlockingConnection")
    @mock.patch("pika.URLParameters")
    async def test_get_sync_connection(
        self, mock_url_parameters, mock_blocking_connection
    ):
        """Test get_sync_connection method"""
        # Setup mocks
        mock_url_parameters.return_value = "mocked_params"
        mock_connection = mock.MagicMock(spec=BlockingConnection)
        mock_blocking_connection.return_value = mock_connection

        # Call the method
        result = self.hook.get_sync_connection()

        # Assertions
        mock_url_parameters.assert_called_once_with(self.connection_uri)
        mock_blocking_connection.assert_called_once_with("mocked_params")
        assert result == mock_connection

    @mock.patch("pika.BlockingConnection")
    @mock.patch("pika.URLParameters")
    async def test_get_sync_connection_cm(
        self, mock_url_parameters, mock_blocking_connection
    ):
        """Test get_sync_connection_cm method"""
        # Setup mocks
        mock_url_parameters.return_value = "mocked_params"
        mock_connection = mock.MagicMock(spec=BlockingConnection)
        mock_connection.is_open = True
        mock_blocking_connection.return_value = mock_connection

        # Call the method
        with self.hook.get_sync_connection_cm() as conn:
            assert conn == mock_connection

        # Assertions
        mock_url_parameters.assert_called_once_with(self.connection_uri)
        mock_blocking_connection.assert_called_once_with("mocked_params")
        mock_connection.close.assert_called_once()

    @mock.patch("pika.BlockingConnection")
    def test_get_sync_connection_cm_lets_body_errors_through(
        self, mock_blocking_connection: mock.MagicMock
    ) -> None:
        """Only opening the connection is reported as ConnectionError"""
        mock_blocking_connection.return_value.is_open = True

        with pytest.raises(KeyError):
            with self.hook.get_sync_connection_cm():
                raise KeyError("not a connection problem")

        mock_blocking_connection.return_value.close.assert_called_once()

    @mock.patch("pika.BlockingConnection", side_effect=OSError("refused"))
    def test_get_sync_connection_cm_wraps_connect_errors(self, _) -> None:
        with pytest.raises(ConnectionError, match="refused"):
            with self.hook.get_sync_connection_cm():
                pass  # pragma: no cover

    @mock.patch("aio_pika.connect_robust")
    async def test_get_async_connection(self, mock_connect_robust):
        """Test get_async_connection method"""
        # Setup mock
        mock_connection = mock.MagicMock(spec=aio_pika.abc.AbstractRobustConnection)
        mock_connect_robust.return_value = mock_connection

        # Call the method
        result = await self.hook.get_async_connection()

        # Assertions
        mock_connect_robust.assert_called_once_with(
            self.connection_uri, ssl_context=None
        )
        assert result == mock_connection

    @mock.patch("airflow.provider.rabbitmq.hooks.rabbitmq_hook.BaseHook.get_connection")
    @mock.patch("pika.BlockingConnection")
    def test_get_sync_connection_with_tls_extras(
        self, mock_blocking_connection, mock_get_connection
    ) -> None:
        """The ssl extra connects to amqps on 5671 with the context from the extras"""
        mock_get_connection.return_value = mock.MagicMock(
            host="rabbitmq",
            port=None,
            login="guest",
            password="guest",
            schema=None,
            extra_dejson={"ssl": True, "ssl_server_hostname": "rabbit.internal"},
        )

        RabbitMQHook(conn_id="tls").get_sync_connection()

        params = mock_blocking_connection.call_args.args[0]
        assert params.port == 5671
        assert params.ssl_options.context.server_hostname == "rabbit.internal"
        mock_get_connection.assert_called_once_with("tls")

    @mock.patch("airflow.provider.rabbitmq.hooks.rabbitmq_hook.BaseHook.get_connection")
    @mock.patch("aio_pika.connect_robust")
    async def test_get_async_connection_with_tls_extras(
        self, mock_connect_robust, mock_get_connection
    ) -> None:
        mock_get_connection.return_value = mock.MagicMock(
            host="rabbitmq",
            port=None,
            login=None,
            password=None,
            schema=None,
            extra_dejson={"ssl": True, "ssl_verify": False},
        )

        await RabbitMQHook(conn_id="tls").get_async_connection()

        uri = mock_connect_robust.call_args.args[0]
        ssl_context = mock_connect_robust.call_args.kwargs["ssl_context"]
        assert uri == "amqps://rabbitmq:5671"
        assert ssl_context.verify_mode == ssl.CERT_NONE

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    async def test_publish_sync(self, mock_get_sync_connection_cm):
        """Test publish_sync method"""
        # Setup mocks
        mock_connection = mock.MagicMock(spec=BlockingConnection)
        mock_channel = mock.MagicMock(spec=pika.channel.Channel)
        mock_connection.channel.return_value = mock_channel

        # Setup context manager
        @contextmanager
        def mock_cm():
            yield mock_connection

        mock_get_sync_connection_cm.return_value = mock_cm()

        # Test data
        message = "test message"
        exchange = "test_exchange"
        routing_key = "test_routing_key"

        # Call the method
        self.hook.publish_sync(message, exchange, routing_key)

        # Assertions
        mock_get_sync_connection_cm.assert_called_once()
        mock_connection.channel.assert_called_once()
        mock_channel.confirm_delivery.assert_called_once_with()
        mock_channel.basic_publish.assert_called_once_with(
            exchange=exchange,
            routing_key=routing_key,
            body=message.encode(),
            properties=pika.BasicProperties(),
            mandatory=False,
        )

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    def test_publish_sync_without_confirm(
        self, mock_get_sync_connection_cm: mock.MagicMock
    ) -> None:
        mock_connection = mock.MagicMock(spec=BlockingConnection)
        mock_get_sync_connection_cm.return_value.__enter__.return_value = (
            mock_connection
        )

        self._hook(confirm=False).publish_sync("m", "ex", "key")

        channel = mock_connection.channel.return_value
        channel.confirm_delivery.assert_not_called()
        channel.basic_publish.assert_called_once()

    @pytest.mark.parametrize(
        "error, reason",
        [
            (pika.exceptions.UnroutableError, MessageNotDeliveredError.UNROUTABLE),
            (pika.exceptions.NackError, MessageNotDeliveredError.NACKED),
        ],
    )
    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    def test_publish_sync_raises_when_broker_refuses(
        self, mock_get_sync_connection_cm: mock.MagicMock, error, reason
    ) -> None:
        """pika's confirm errors become MessageNotDeliveredError"""
        mock_connection = mock.MagicMock(spec=BlockingConnection)
        mock_get_sync_connection_cm.return_value.__enter__.return_value = (
            mock_connection
        )
        returned = ReturnedMessage(
            pika.spec.Basic.Return(312, "NO_ROUTE", "ex", "key"),
            pika.BasicProperties(),
            b"m",
        )
        channel = mock_connection.channel.return_value
        channel.basic_publish.side_effect = error([returned])

        with pytest.raises(MessageNotDeliveredError) as excinfo:
            self._hook(mandatory=True).publish_sync("m", "ex", "key")

        assert excinfo.value.reason == reason
        assert (excinfo.value.exchange, excinfo.value.routing_key) == ("ex", "key")
        assert isinstance(excinfo.value.__cause__, error)
        assert channel.basic_publish.call_args.kwargs["mandatory"] is True

    def test_init_rejects_mandatory_without_confirm(self) -> None:
        with pytest.raises(ValueError, match="mandatory=True requires confirm=True"):
            self._hook(confirm=False, mandatory=True)

    def test_init_delivery_defaults(self) -> None:
        assert (self.hook.confirm, self.hook.mandatory) == (True, False)

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    async def test_publish_sync_with_bytes_and_properties(
        self, mock_get_sync_connection_cm
    ):
        mock_connection = mock.MagicMock(spec=BlockingConnection)
        mock_get_sync_connection_cm.return_value.__enter__.return_value = (
            mock_connection
        )

        self.hook.publish_sync(
            b"\xff", "ex", "key", properties={"delivery_mode": 2, "headers": {"a": 1}}
        )

        _, kwargs = mock_connection.channel.return_value.basic_publish.call_args
        assert kwargs["body"] == b"\xff"
        assert kwargs["properties"].delivery_mode == 2
        assert kwargs["properties"].headers == {"a": 1}

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    async def test_publish_sync_rejects_invalid_properties_before_connecting(
        self, mock_get_sync_connection_cm
    ):
        with pytest.raises(ValueError, match="Unknown message properties: persistent"):
            self.hook.publish_sync("m", "ex", "key", properties={"persistent": True})

        mock_get_sync_connection_cm.assert_not_called()

    def test_pika_properties_keep_every_key(self):
        props = build_pika_properties(ALL_PROPERTIES)

        for key, value in ALL_PROPERTIES.items():
            assert getattr(props, key) == value, key

    def test_aio_pika_message_keeps_every_key(self):
        message = build_aio_pika_message("body", ALL_PROPERTIES)

        assert message.body == b"body"
        assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
        assert message.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)
        # aio-pika takes expiration as a duration and sends it as milliseconds.
        assert message.expiration == timedelta(seconds=60)
        assert message.properties.expiration == "60000"
        for key in ALL_PROPERTIES.keys() - {"delivery_mode", "timestamp", "expiration"}:
            assert getattr(message, key) == ALL_PROPERTIES[key], key

    @pytest.mark.parametrize(
        "properties,expected",
        [
            ({"delivery_mode": "2"}, {"delivery_mode": 2}),
            ({"priority": "9"}, {"priority": 9}),
            ({"expiration": 1500}, {"expiration": "1500"}),
            ({"expiration": timedelta(seconds=2)}, {"expiration": "2000"}),
            (
                {"timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc)},
                {"timestamp": 1704067200},
            ),
            ({"timestamp": "1704067200"}, {"timestamp": 1704067200}),
            ({"correlation_id": None}, {}),
            (None, {}),
        ],
    )
    def test_normalize_properties_converts_rendered_values(self, properties, expected):
        assert normalize_properties(properties) == expected

    @pytest.mark.parametrize(
        "properties,error",
        [
            ({"persistent": True}, "Unknown message properties"),
            ({"delivery_mode": 3}, "delivery_mode"),
            ({"priority": 256}, "priority"),
            ({"expiration": -1}, "expiration"),
            ({"headers": "a=1"}, "headers"),
        ],
    )
    def test_normalize_properties_rejects_invalid_values(self, properties, error):
        with pytest.raises(ValueError, match=error):
            normalize_properties(properties)

    @staticmethod
    def _mock_async_connection(
        mock_get_async_connection: mock.MagicMock,
    ) -> mock.MagicMock:
        """Wire up a mocked async connection and return its channel."""
        mock_connection = mock.MagicMock(spec=aio_pika.abc.AbstractRobustConnection)
        mock_channel = mock.MagicMock(spec=aio_pika.abc.AbstractChannel)
        mock_channel.default_exchange = mock.MagicMock()
        mock_channel.default_exchange.publish = mock.AsyncMock()
        mock_channel.get_exchange = mock.AsyncMock()
        mock_channel.get_exchange.return_value.publish = mock.AsyncMock()

        mock_connection.channel = mock.AsyncMock(return_value=mock_channel)
        mock_connection.close = mock.AsyncMock()
        mock_get_async_connection.return_value = mock_connection
        return mock_channel

    @mock.patch.object(RabbitMQHook, "get_async_connection")
    async def test_publish_async_to_named_exchange(
        self, mock_get_async_connection: mock.MagicMock
    ) -> None:
        """publish_async publishes through the named exchange, checked passively"""
        mock_channel = self._mock_async_connection(mock_get_async_connection)

        await self.hook.publish_async("test message", "test_exchange", "test_key")

        mock_channel.get_exchange.assert_awaited_once_with("test_exchange", ensure=True)
        named_exchange = mock_channel.get_exchange.return_value
        named_exchange.publish.assert_awaited_once()
        published, kwargs = named_exchange.publish.await_args
        assert published[0].body == b"test message"
        assert published[0].delivery_mode == aio_pika.DeliveryMode.NOT_PERSISTENT
        assert kwargs == {"routing_key": "test_key", "mandatory": False}
        mock_get_async_connection.return_value.channel.assert_awaited_once_with(
            publisher_confirms=True, on_return_raises=False
        )
        mock_channel.default_exchange.publish.assert_not_awaited()
        mock_get_async_connection.return_value.close.assert_awaited_once()

    @mock.patch.object(RabbitMQHook, "get_async_connection")
    async def test_publish_async_to_default_exchange(
        self, mock_get_async_connection: mock.MagicMock
    ) -> None:
        """publish_async uses the default exchange when exchange is empty"""
        mock_channel = self._mock_async_connection(mock_get_async_connection)

        await self.hook.publish_async("test message", "", "test_queue")

        mock_channel.get_exchange.assert_not_awaited()
        mock_channel.default_exchange.publish.assert_awaited_once()
        _, kwargs = mock_channel.default_exchange.publish.await_args
        assert kwargs == {"routing_key": "test_queue", "mandatory": False}
        mock_get_async_connection.return_value.close.assert_awaited_once()

    @mock.patch.object(RabbitMQHook, "get_async_connection")
    async def test_publish_async_with_bytes_and_properties(
        self, mock_get_async_connection: mock.MagicMock
    ) -> None:
        mock_channel = self._mock_async_connection(mock_get_async_connection)

        await self.hook.publish_async(
            b"\xff",
            "",
            "test_queue",
            properties={"delivery_mode": 2, "content_type": "application/octet-stream"},
        )

        published, _ = mock_channel.default_exchange.publish.await_args
        assert published[0].body == b"\xff"
        assert published[0].delivery_mode == aio_pika.DeliveryMode.PERSISTENT
        assert published[0].content_type == "application/octet-stream"

    @mock.patch.object(RabbitMQHook, "get_async_connection")
    async def test_publish_async_rejects_invalid_properties_before_connecting(
        self, mock_get_async_connection: mock.MagicMock
    ) -> None:
        with pytest.raises(ValueError, match="priority"):
            await self.hook.publish_async("m", "", "q", properties={"priority": -1})

        mock_get_async_connection.assert_not_called()

    @mock.patch.object(RabbitMQHook, "get_async_connection")
    async def test_publish_async_delivery_options_open_the_channel(
        self, mock_get_async_connection: mock.MagicMock
    ) -> None:
        mock_channel = self._mock_async_connection(mock_get_async_connection)

        await self._hook(confirm=False).publish_async("m", "", "q")
        await self._hook(mandatory=True).publish_async("m", "", "q")

        channel = mock_get_async_connection.return_value.channel
        assert channel.await_args_list == [
            mock.call(publisher_confirms=False, on_return_raises=False),
            mock.call(publisher_confirms=True, on_return_raises=True),
        ]
        last_publish = mock_channel.default_exchange.publish.await_args
        assert last_publish.kwargs["mandatory"] is True

    @pytest.mark.parametrize(
        "error, reason",
        [
            (
                aio_pika.exceptions.PublishError(
                    aiormq.abc.DeliveredMessage(
                        delivery=aiormq.spec.Basic.Return(
                            reply_code=312, reply_text="NO_ROUTE", routing_key="q"
                        ),
                        header=None,
                        body=b"m",
                        channel=None,
                    ),
                    None,
                ),
                MessageNotDeliveredError.UNROUTABLE,
            ),
            (
                aio_pika.exceptions.DeliveryError(None, aiormq.spec.Basic.Nack()),
                MessageNotDeliveredError.NACKED,
            ),
        ],
    )
    @mock.patch.object(RabbitMQHook, "get_async_connection")
    async def test_publish_async_raises_when_broker_refuses(
        self, mock_get_async_connection: mock.MagicMock, error, reason
    ) -> None:
        """aio-pika's confirm errors become MessageNotDeliveredError"""
        mock_channel = self._mock_async_connection(mock_get_async_connection)
        mock_channel.default_exchange.publish.side_effect = error

        with pytest.raises(MessageNotDeliveredError) as excinfo:
            await self._hook(mandatory=True).publish_async("m", "", "q")

        assert excinfo.value.reason == reason
        assert excinfo.value.__cause__ is error
        mock_get_async_connection.return_value.close.assert_awaited_once()

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    def test_publish_batch_sync_uses_one_channel(
        self, mock_get_sync_connection_cm: mock.MagicMock
    ) -> None:
        """A batch goes out in order over one channel, with per-item overrides"""
        mock_connection = mock.MagicMock(spec=BlockingConnection)
        mock_get_sync_connection_cm.return_value.__enter__.return_value = (
            mock_connection
        )

        count = self.hook.publish_batch_sync(
            [
                "a",
                b"b",
                {"body": "c", "routing_key": "other", "properties": {"priority": 1}},
                {"message": "d", "exchange": "ex2"},
            ],
            "ex",
            "key",
            properties={"delivery_mode": 2},
        )

        assert count == 4
        mock_get_sync_connection_cm.assert_called_once()
        mock_connection.channel.assert_called_once()
        calls = mock_connection.channel.return_value.basic_publish.call_args_list
        assert [
            (c.kwargs["exchange"], c.kwargs["routing_key"], c.kwargs["body"])
            for c in calls
        ] == [
            ("ex", "key", b"a"),
            ("ex", "key", b"b"),
            ("ex", "other", b"c"),
            ("ex2", "key", b"d"),
        ]
        assert all(c.kwargs["properties"].delivery_mode == 2 for c in calls)
        assert calls[2].kwargs["properties"].priority == 1

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    def test_publish_batch_sync_empty_does_not_connect(
        self, mock_get_sync_connection_cm: mock.MagicMock
    ) -> None:
        assert self.hook.publish_batch_sync([], "ex", "key") == 0

        mock_get_sync_connection_cm.assert_not_called()

    @mock.patch.object(RabbitMQHook, "get_sync_connection_cm")
    def test_publish_batch_sync_rejects_invalid_item_before_connecting(
        self, mock_get_sync_connection_cm: mock.MagicMock
    ) -> None:
        """One bad item fails the whole batch before anything is sent"""
        with pytest.raises(ValueError, match="priority"):
            self.hook.publish_batch_sync(
                ["ok", {"body": "bad", "properties": {"priority": -1}}], "ex", "key"
            )

        mock_get_sync_connection_cm.assert_not_called()

    @mock.patch.object(RabbitMQHook, "get_async_connection")
    async def test_publish_batch_async_uses_one_channel(
        self, mock_get_async_connection: mock.MagicMock
    ) -> None:
        """A batch goes out in order over one channel, with per-item overrides"""
        mock_channel = self._mock_async_connection(mock_get_async_connection)

        count = await self.hook.publish_batch_async(
            ["a", {"body": b"b", "exchange": "ex", "routing_key": "rk"}, "c"],
            "",
            "q",
        )

        assert count == 3
        mock_get_async_connection.assert_awaited_once()
        mock_get_async_connection.return_value.channel.assert_awaited_once()
        default_publishes = mock_channel.default_exchange.publish.await_args_list
        assert [(c.args[0].body, c.kwargs) for c in default_publishes] == [
            (b"a", {"routing_key": "q", "mandatory": False}),
            (b"c", {"routing_key": "q", "mandatory": False}),
        ]
        mock_channel.get_exchange.assert_awaited_once_with("ex", ensure=True)
        named_publish = mock_channel.get_exchange.return_value.publish
        assert named_publish.await_args.args[0].body == b"b"
        assert named_publish.await_args.kwargs == {
            "routing_key": "rk",
            "mandatory": False,
        }
        mock_get_async_connection.return_value.close.assert_awaited_once()

    @mock.patch.object(RabbitMQHook, "get_async_connection")
    async def test_publish_batch_async_empty_does_not_connect(
        self, mock_get_async_connection: mock.MagicMock
    ) -> None:
        assert await self.hook.publish_batch_async([], "", "q") == 0

        mock_get_async_connection.assert_not_called()
