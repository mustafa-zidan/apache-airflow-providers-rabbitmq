from unittest import mock

import pytest


@pytest.fixture
def mock_rabbitmq_connection():
    """Fixture to mock a RabbitMQ connection"""
    with mock.patch("pika.BlockingConnection") as mock_conn:
        yield mock_conn


@pytest.fixture
def mock_rabbitmq_channel():
    """Fixture to mock a RabbitMQ channel"""
    with mock.patch("pika.channel.Channel") as mock_channel:
        yield mock_channel


@pytest.fixture
def mock_async_rabbitmq_connection():
    """Fixture to mock an async RabbitMQ connection"""
    with mock.patch("aio_pika.connect_robust") as mock_conn:
        yield mock_conn


@pytest.fixture
def mock_async_rabbitmq_channel():
    """Fixture to mock an async RabbitMQ channel"""
    with mock.patch("aio_pika.abc.AbstractChannel") as mock_channel:
        yield mock_channel


@pytest.fixture
def mock_rabbitmq_hook():
    """Fixture to mock the RabbitMQHook"""
    with mock.patch(
        "airflow.provider.rabbitmq.hooks.rabbitmq_hook.RabbitMQHook"
    ) as mock_hook:
        yield mock_hook
