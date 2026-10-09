"""Tests for provider metadata."""

import importlib
import re
import tomllib
from pathlib import Path

import pytest
import yaml

from airflow.provider.rabbitmq.get_provider_info import get_provider_info

ROOT = Path(__file__).resolve().parents[2]
PROVIDER_YAML = ROOT / "src/airflow/provider/rabbitmq/provider.yaml"
LEGACY_PROVIDER_YAML = ROOT / "src/airflow/providers/rabbitmq/provider.yaml"


def _project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def _yaml_versions() -> list[str]:
    return [str(v) for v in yaml.safe_load(PROVIDER_YAML.read_text())["versions"]]


def test_connection_form_has_no_schema_relabeling() -> None:
    """Relabeling schema breaks saving the connection in the Airflow 3.2+ UI (#23)."""
    (connection_type,) = get_provider_info()["connection-types"]

    assert "relabeling" not in connection_type["ui-field-behaviour"]


def test_connection_form_placeholders_are_strings() -> None:
    """Airflow drops the ui-field-behaviour block if a placeholder isn't a string."""
    (connection_type,) = yaml.safe_load(PROVIDER_YAML.read_text())["connection-types"]
    placeholders = connection_type["ui-field-behaviour"]["placeholders"]

    assert all(isinstance(value, str) for value in placeholders.values())


def test_provider_yaml_connection_types_match_provider_info() -> None:
    """provider.yaml declares the same connection types as get_provider_info()."""
    provider_yaml = yaml.safe_load(PROVIDER_YAML.read_text())

    assert provider_yaml["connection-types"] == get_provider_info()["connection-types"]


def test_provider_yaml_latest_version_matches_pyproject() -> None:
    """The newest provider.yaml version is the version being packaged."""
    assert _yaml_versions()[0] == _project_version()


def test_provider_yaml_lists_every_released_version() -> None:
    """Every version in RELEASE_NOTES.md appears in provider.yaml, newest first."""
    released = re.findall(
        r"^## Version (\d+\.\d+\.\d+)", (ROOT / "RELEASE_NOTES.md").read_text(), re.M
    )
    versions = _yaml_versions()

    assert not set(released) - set(versions)
    assert versions == sorted(
        versions, key=lambda v: tuple(int(p) for p in v.split(".")), reverse=True
    )


def test_legacy_provider_yaml_matches_canonical() -> None:
    """The legacy namespace ships the same provider.yaml as the canonical one."""
    assert LEGACY_PROVIDER_YAML.read_text() == PROVIDER_YAML.read_text()


def test_package_version_defaults_to_pyproject_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """__version__ falls back to the pyproject version in both namespaces."""
    monkeypatch.delenv("PACKAGE_VERSION", raising=False)
    version = importlib.reload(
        importlib.import_module("airflow.provider.rabbitmq.version")
    )
    package = importlib.reload(importlib.import_module("airflow.provider.rabbitmq"))
    legacy = importlib.reload(importlib.import_module("airflow.providers.rabbitmq"))

    assert version.__version__ == _project_version()
    assert package.__version__ == _project_version()
    assert legacy.__version__ == _project_version()


def test_get_provider_info_exposes_airflow_metadata() -> None:
    """Provider info exposes the expected Airflow metadata."""
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
            "ui-field-behaviour": {
                "placeholders": {"host": "localhost", "port": "5672", "schema": "/"},
            },
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
            "python-modules": ["airflow.provider.rabbitmq.operators.rabbitmq_producer"],
        }
    ]
    assert provider_info["sensors"] == [
        {
            "integration-name": "RabbitMQ",
            "python-modules": ["airflow.provider.rabbitmq.sensors.rabbitmq_sensor"],
        }
    ]
    assert provider_info["triggers"] == [
        {
            "integration-name": "RabbitMQ",
            "python-modules": ["airflow.provider.rabbitmq.triggers.rabbitmq_trigger"],
        }
    ]


def test_pyproject_registers_airflow_provider_entry_point() -> None:
    """pyproject registers the apache_airflow_provider entry point."""
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
