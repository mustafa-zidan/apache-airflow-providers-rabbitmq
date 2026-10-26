"""Integration tests using a RabbitMQ container."""

import json
import os
from typing import Any, Dict
from unittest import mock

import aio_pika
import pika
import pytest

try:
    import docker
    from docker.errors import DockerException
    from testcontainers.rabbitmq import RabbitMqContainer

    # Try to ping docker to see if it's actually running
    docker.from_env().ping()
    DOCKER_AVAILABLE = True
except (ImportError, DockerException, OSError):
    DOCKER_AVAILABLE = False

from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker is not available")
class TestRabbitMQIntegration:
    """Integration tests for RabbitMQ provider components"""

    queue: str = "test_queue"
    routing_key: str = "test_queue"
    exchange: str = ""
    message: str = "test integration message"
    task_id: str = "test_task_id"
    conn_id: str = "rabbitmq_integration"
    connection_uri: str = None
    named_exchange: str = "test_exchange"
    named_exchange_queue: str = "test_exchange_queue"
    named_exchange_routing_key: str = "test_exchange_key"

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def rabbitmq_container(cls):
        """Start a RabbitMQ container for the test class"""
        with RabbitMqContainer("rabbitmq:4") as container:
            # Allow RabbitMQ to initialize
            params = container.get_connection_params()
            creds = f"{params.credentials.username}:{params.credentials.password}"
            cls.connection_uri = (
                f"amqp://{creds}@{params.host}:{params.port}{params.virtual_host}"
            )

            # Manually configure queue using pika
            params = pika.URLParameters(cls.connection_uri)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=cls.queue, durable=True)
            channel.exchange_declare(
                exchange=cls.named_exchange, exchange_type="direct"
            )
            channel.queue_declare(queue=cls.named_exchange_queue, durable=True)
            channel.queue_bind(
                queue=cls.named_exchange_queue,
                exchange=cls.named_exchange,
                routing_key=cls.named_exchange_routing_key,
            )
            connection.close()  # no need for this connection anymore

            # Expose the broker to the operator and sensor as an Airflow connection
            airflow_conn = json.dumps(
                {
                    "conn_type": "rabbitmq",
                    "extra": {"connection_uri": cls.connection_uri},
                }
            )
            with mock.patch.dict(
                os.environ, {f"AIRFLOW_CONN_{cls.conn_id.upper()}": airflow_conn}
            ):
                yield  # continue with tests

    def test_operator_sensor_integration(self):
        """Test integration between RabbitMQProducerOperator and RabbitMQSensor"""
        # Run the RabbitMQProducerOperator
        operator = RabbitMQProducerOperator(
            task_id=TestRabbitMQIntegration.task_id,
            conn_id=TestRabbitMQIntegration.conn_id,
            message=TestRabbitMQIntegration.message,
            exchange=TestRabbitMQIntegration.exchange,
            routing_key=TestRabbitMQIntegration.routing_key,
            use_async=False,
        )

        context: Dict[str, Any] = {}
        operator.execute(context)

        # Run the RabbitMQSensor to verify the message
        sensor = RabbitMQSensor(
            task_id=TestRabbitMQIntegration.task_id,
            conn_id=TestRabbitMQIntegration.conn_id,
            queue_name=TestRabbitMQIntegration.queue,
            timeout=10,  # seconds
            poke_interval=1,
            mode="poke",
        )

        result = sensor.poke(context)
        assert result.is_done is True
        assert result.xcom_value["body"] == TestRabbitMQIntegration.message
        assert result.xcom_value["routing_key"] == TestRabbitMQIntegration.routing_key

    def test_sensor_returns_json_message_with_properties(self) -> None:
        """The sensor parses a JSON body and returns the message properties"""
        connection = pika.BlockingConnection(pika.URLParameters(self.connection_uri))
        try:
            connection.channel().basic_publish(
                exchange="",
                routing_key=self.queue,
                body=json.dumps({"order_id": 42}).encode(),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    message_id="m-1",
                    headers={"source": "shop"},
                ),
            )
        finally:
            connection.close()
        sensor = RabbitMQSensor(
            task_id=self.task_id,
            conn_id=self.conn_id,
            queue_name=self.queue,
            deserialize="json",
        )

        result = sensor.poke({})

        assert result.xcom_value["body"] == {"order_id": 42}
        assert result.xcom_value["content_type"] == "application/json"
        assert result.xcom_value["message_id"] == "m-1"
        assert result.xcom_value["headers"] == {"source": "shop"}
        assert self._get_message(self.queue) is None  # acked

    def test_sensor_without_auto_ack_leaves_message_on_queue(self) -> None:
        """auto_ack=False returns the message and puts it back on the queue"""
        connection = pika.BlockingConnection(pika.URLParameters(self.connection_uri))
        try:
            connection.channel().basic_publish(
                exchange="", routing_key=self.queue, body=b"peek me"
            )
        finally:
            connection.close()
        sensor = RabbitMQSensor(
            task_id=self.task_id,
            conn_id=self.conn_id,
            queue_name=self.queue,
            auto_ack=False,
        )

        result = sensor.poke({})

        assert result.xcom_value["body"] == "peek me"
        assert self._get_message(self.queue) == b"peek me"

    def _get_message(self, queue: str) -> bytes | None:
        """Take one message off a queue, or None if it's empty."""
        connection = pika.BlockingConnection(pika.URLParameters(self.connection_uri))
        try:
            method_frame, _, body = connection.channel().basic_get(queue, auto_ack=True)
            return body if method_frame else None
        finally:
            connection.close()

    def _publish_async(self, message: str, exchange: str, routing_key: str) -> None:
        RabbitMQProducerOperator(
            task_id=self.task_id,
            conn_id=self.conn_id,
            message=message,
            exchange=exchange,
            routing_key=routing_key,
            use_async=True,
        ).execute({})

    def test_async_publish_to_named_exchange(self) -> None:
        """use_async=True routes through the named exchange, not the default one"""
        self._publish_async(
            "via named exchange", self.named_exchange, self.named_exchange_routing_key
        )

        assert self._get_message(self.named_exchange_queue) == b"via named exchange"

    def test_async_publish_to_default_exchange(self) -> None:
        """use_async=True with an empty exchange publishes straight to the queue"""
        self._publish_async("via default exchange", "", self.queue)

        assert self._get_message(self.queue) == b"via default exchange"

    def test_async_publish_to_missing_exchange_fails(self) -> None:
        """use_async=True fails the task when the exchange doesn't exist"""
        with pytest.raises(aio_pika.exceptions.ChannelNotFoundEntity):
            self._publish_async("lost", "missing_exchange", self.routing_key)

    @pytest.mark.parametrize("use_async", [False, True])
    def test_publish_with_properties(self, use_async: bool) -> None:
        """Message properties survive the broker on both publish paths"""
        RabbitMQProducerOperator(
            task_id=self.task_id,
            conn_id=self.conn_id,
            message=b"\x00binary",
            exchange="",
            routing_key=self.queue,
            use_async=use_async,
            properties={
                "content_type": "application/octet-stream",
                "delivery_mode": 2,
                "headers": {"source": "airflow"},
                "priority": 5,
                "correlation_id": "run-1",
                "expiration": "60000",
            },
        ).execute({})

        connection = pika.BlockingConnection(pika.URLParameters(self.connection_uri))
        try:
            method_frame, properties, body = connection.channel().basic_get(
                self.queue, auto_ack=True
            )
        finally:
            connection.close()

        assert method_frame is not None
        assert body == b"\x00binary"
        assert properties.content_type == "application/octet-stream"
        assert properties.delivery_mode == 2
        assert properties.headers == {"source": "airflow"}
        assert properties.priority == 5
        assert properties.correlation_id == "run-1"
        assert properties.expiration == "60000"

    @pytest.mark.parametrize("use_async", [False, True])
    def test_publish_batch_over_one_connection(self, use_async: bool) -> None:
        """A list of 100 messages lands on the queue through a single connection"""
        queue = f"batch_queue_{'async' if use_async else 'sync'}"
        connection = pika.BlockingConnection(pika.URLParameters(self.connection_uri))
        try:
            connection.channel().queue_declare(queue=queue, durable=True)
        finally:
            connection.close()
        operator = RabbitMQProducerOperator(
            task_id=self.task_id,
            conn_id=self.conn_id,
            message=[f"m{i}" for i in range(100)],
            exchange="",
            routing_key=queue,
            use_async=use_async,
        )

        if use_async:
            with mock.patch(
                "aio_pika.connect_robust", wraps=aio_pika.connect_robust
            ) as connect:
                count = operator.execute({})
        else:
            with mock.patch(
                "pika.BlockingConnection", wraps=pika.BlockingConnection
            ) as connect:
                count = operator.execute({})

        assert count == 100
        assert connect.call_count == 1
        assert self._message_count(queue) == 100
        assert self._get_message(queue) == b"m0"

    def test_publish_batch_routes_each_item(self) -> None:
        """Dict items override the routing key and exchange per message"""
        RabbitMQProducerOperator(
            task_id=self.task_id,
            conn_id=self.conn_id,
            message=[
                "to default queue",
                {
                    "body": "to named exchange",
                    "exchange": self.named_exchange,
                    "routing_key": self.named_exchange_routing_key,
                },
            ],
            exchange="",
            routing_key=self.queue,
        ).execute({})

        assert self._get_message(self.queue) == b"to default queue"
        assert self._get_message(self.named_exchange_queue) == b"to named exchange"

    def _message_count(self, queue: str) -> int:
        """Ready messages on a queue, polled briefly while the broker catches up."""
        connection = pika.BlockingConnection(pika.URLParameters(self.connection_uri))
        try:
            channel = connection.channel()
            for _ in range(20):
                count = channel.queue_declare(queue, passive=True).method.message_count
                if count:
                    return count
                connection.sleep(0.1)
            return count
        finally:
            connection.close()
