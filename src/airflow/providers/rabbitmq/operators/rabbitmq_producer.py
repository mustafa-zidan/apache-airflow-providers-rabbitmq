# Compatibility shim — redirects to new canonical namespace airflow.provider.rabbitmq
from airflow.provider.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator  # noqa: F401

__all__ = ["RabbitMQProducerOperator"]
