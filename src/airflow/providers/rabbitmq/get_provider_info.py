# Compatibility shim — redirects to new canonical namespace airflow.provider.rabbitmq
from airflow.provider.rabbitmq.get_provider_info import get_provider_info  # noqa: F401

__all__ = ["get_provider_info"]
