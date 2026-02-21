from contextlib import contextmanager
from unittest import mock

import aio_pika
import pika
import pytest
from pika.adapters.blocking_connection import BlockingConnection

from airflow.providers.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook


class TestRabbitMQHook:
    """Tests for RabbitMQHook"""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up test fixtures"""
        self.connection_uri = "amqp://guest:guest@localhost:5672/"
        self.conn_id = "rabbitmq_default"
        self.hook = RabbitMQHook(connection_uri=self.connection_uri)

    async def test_init(self):
        """Test hook initialization"""
        # Test with connection_uri
        hook1 = RabbitMQHook(connection_uri=self.connection_uri)
        assert hook1._connection_uri == self.connection_uri
        assert hook1.conn_id == "rabbitmq_default"

        # Test with conn_id
        hook2 = RabbitMQHook(conn_id="test_conn")
        assert hook2._connection_uri is None
        assert hook2.conn_id == "test_conn"

    @mock.patch(
        "airflow.providers.rabbitmq.hooks.rabbitmq_hook.BaseHook.get_connection"
    )
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

    @mock.patch("aio_pika.connect_robust")
    async def test_get_async_connection(self, mock_connect_robust):
        """Test get_async_connection method"""
        # Setup mock
        mock_connection = mock.MagicMock(spec=aio_pika.abc.AbstractRobustConnection)
        mock_connect_robust.return_value = mock_connection

        # Call the method
        result = await self.hook.get_async_connection()

        # Assertions
        mock_connect_robust.assert_called_once_with(self.connection_uri)
        assert result == mock_connection

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
        mock_channel.basic_publish.assert_called_once_with(
            exchange=exchange, routing_key=routing_key, body=message
        )

    @mock.patch.object(RabbitMQHook, "get_async_connection")
    async def test_publish_async(self, mock_get_async_connection):
        """Test publish_async method"""
        # Setup mocks
        mock_connection = mock.MagicMock(spec=aio_pika.abc.AbstractRobustConnection)
        mock_channel = mock.MagicMock(spec=aio_pika.abc.AbstractChannel)
        mock_exchange = mock.MagicMock()
        mock_channel.default_exchange = mock_exchange

        # Setup async context
        mock_connection.channel = mock.AsyncMock(return_value=mock_channel)
        mock_connection.close = mock.AsyncMock()
        mock_exchange.publish = mock.AsyncMock()
        mock_get_async_connection.return_value = mock_connection

        # Test data
        message = "test message"
        exchange = "test_exchange"
        routing_key = "test_routing_key"

        # Call the method
        await self.hook.publish_async(message, exchange, routing_key)

        # Assertions
        mock_get_async_connection.assert_called_once()
        mock_connection.channel.assert_called_once()
        mock_exchange.publish.assert_called_once()
        mock_connection.close.assert_called_once()
