# Compatibility shim — redirects to new canonical namespace airflow.provider.rabbitmq
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import (  # noqa: F401
    RabbitMQSensor,
)

__all__ = ["RabbitMQSensor"]
