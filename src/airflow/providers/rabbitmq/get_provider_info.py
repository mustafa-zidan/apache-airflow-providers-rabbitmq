from __future__ import annotations

from typing import Any


def get_provider_info() -> dict[str, Any]:
    """Return the metadata Airflow uses to discover this provider."""
    return {
        "package-name": "apache-airflow-provider-rabbitmq",
        "name": "RabbitMQ",
        "description": "Airflow provider for RabbitMQ with sync/async messaging.",
        "integrations": [
            {
                "integration-name": "RabbitMQ",
                "external-doc-url": (
                    "https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq"
                ),
                "tags": ["software"],
            }
        ],
        "hook-class-names": [
            "airflow.providers.rabbitmq.hooks.rabbitmq_hook.RabbitMQHook"
        ],
        "connection-types": [
            {
                "connection-type": "rabbitmq",
                "hook-class-name": (
                    "airflow.providers.rabbitmq.hooks.rabbitmq_hook.RabbitMQHook"
                ),
            }
        ],
        "hooks": [
            {
                "integration-name": "RabbitMQ",
                "python-modules": ["airflow.providers.rabbitmq.hooks.rabbitmq_hook"],
            }
        ],
        "operators": [
            {
                "integration-name": "RabbitMQ",
                "python-modules": [
                    "airflow.providers.rabbitmq.operators.rabbitmq_producer"
                ],
            }
        ],
        "sensors": [
            {
                "integration-name": "RabbitMQ",
                "python-modules": [
                    "airflow.providers.rabbitmq.sensors.rabbitmq_sensor"
                ],
            }
        ],
    }
