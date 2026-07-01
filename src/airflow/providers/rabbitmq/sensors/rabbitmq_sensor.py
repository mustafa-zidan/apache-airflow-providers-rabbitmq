# Compatibility shim — redirects to new canonical namespace airflow.provider.rabbitmq
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor  # noqa: F401

__all__ = ["RabbitMQSensor"]
