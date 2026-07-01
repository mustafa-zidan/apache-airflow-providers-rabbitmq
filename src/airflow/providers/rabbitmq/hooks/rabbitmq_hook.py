# Compatibility shim — redirects to new canonical namespace airflow.provider.rabbitmq
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook  # noqa: F401

__all__ = ["RabbitMQHook"]
