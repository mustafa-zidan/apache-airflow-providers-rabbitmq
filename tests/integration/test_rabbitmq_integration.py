import unittest
from typing import Any, Dict

import pika
import pytest

try:
    import docker
    from testcontainers.rabbitmq import RabbitMqContainer

    # Try to ping docker to see if it's actually running
    client = docker.from_env()
    client.ping()
    DOCKER_AVAILABLE = True
except Exception:
    DOCKER_AVAILABLE = False

from airflow.providers.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.providers.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker is not available")
class TestRabbitMQIntegration:
    """Integration tests for RabbitMQ provider components"""

    queue: str = "test_queue"
    routing_key: str = "test_queue"
    exchange: str = ""
    message: str = "test integration message"
    task_id: str = "test_task_id"
    connection_uri: str = None

    @pytest.fixture(scope="class", autouse=True)
    def rabbitmq_container(self, request):
        """Start a RabbitMQ container for the test class"""
        print(request)
        with RabbitMqContainer("rabbitmq:4") as container:
            # Allow RabbitMQ to initialize
            params = container.get_connection_params()
            request.cls.connection_uri = f"amqp://{params.credentials.username}:{params.credentials.password}@{params.host}:{params.port}{params.virtual_host}"

            # Manually configure queue using pika
            params = pika.URLParameters(request.cls.connection_uri)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=request.cls.queue, durable=False)
            connection.close()  # no need for this connection anymore

            yield  # continue with tests

    def test_operator_sensor_integration(self):
        """Test integration between RabbitMQProducerOperator and RabbitMQSensor"""
        # Run the RabbitMQProducerOperator
        operator = RabbitMQProducerOperator(
            task_id=TestRabbitMQIntegration.task_id,
            connection_uri=TestRabbitMQIntegration.connection_uri,
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
            connection_uri=TestRabbitMQIntegration.connection_uri,
            queue=TestRabbitMQIntegration.queue,
            timeout=10,  # seconds
            poke_interval=1,
            mode="poke",
        )

        result = sensor.poke(context)
        assert result is True
