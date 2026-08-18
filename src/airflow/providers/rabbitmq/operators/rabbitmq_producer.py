# Compatibility shim — redirects to new canonical namespace airflow.provider.rabbitmq
from airflow.provider.rabbitmq.operators.rabbitmq_producer import (  # noqa: F401
    RabbitMQProducerOperator,
)

__all__ = ["RabbitMQProducerOperator"]
