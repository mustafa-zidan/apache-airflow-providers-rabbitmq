from pathlib import Path

from airflow.provider.rabbitmq.get_provider_info import get_provider_info


def test_get_provider_info_exposes_airflow_metadata() -> None:
    provider_info = get_provider_info()

    assert provider_info["package-name"] == "apache-airflow-provider-rabbitmq"
    assert provider_info["name"] == "RabbitMQ"
    assert provider_info["description"] == (
        "Airflow provider for RabbitMQ with sync/async messaging."
    )
    assert provider_info["integrations"] == [
        {
            "integration-name": "RabbitMQ",
            "external-doc-url": (
                "https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq"
            ),
            "tags": ["software"],
        }
    ]
    assert provider_info["hook-class-names"] == [
        "airflow.provider.rabbitmq.hooks.rabbitmq_hook.RabbitMQHook"
    ]
    assert provider_info["connection-types"] == [
        {
            "connection-type": "rabbitmq",
            "hook-class-name": (
                "airflow.provider.rabbitmq.hooks.rabbitmq_hook.RabbitMQHook"
            ),
        }
    ]
    assert provider_info["hooks"] == [
        {
            "integration-name": "RabbitMQ",
            "python-modules": ["airflow.provider.rabbitmq.hooks.rabbitmq_hook"],
        }
    ]
    assert provider_info["operators"] == [
        {
            "integration-name": "RabbitMQ",
            "python-modules": [
                "airflow.provider.rabbitmq.operators.rabbitmq_producer"
            ],
        }
    ]
    assert provider_info["sensors"] == [
        {
            "integration-name": "RabbitMQ",
            "python-modules": ["airflow.provider.rabbitmq.sensors.rabbitmq_sensor"],
        }
    ]


def test_pyproject_registers_airflow_provider_entry_point() -> None:
    pyproject_toml = Path(__file__).resolve().parents[2] / "pyproject.toml"
    content = pyproject_toml.read_text()

    assert "[project.urls]" in content
    assert (
        "Documentation = "
        '"https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq"'
    ) in content
    assert '[project.entry-points."apache_airflow_provider"]' in content
    assert (
        "provider_info = "
        '"airflow.provider.rabbitmq.get_provider_info:get_provider_info"'
    ) in content
