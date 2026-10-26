# Apache Airflow Provider for RabbitMQ

[![PyPI version](https://img.shields.io/pypi/v/apache-airflow-provider-rabbitmq?logo=python)](https://pypi.org/project/apache-airflow-provider-rabbitmq/)
[![License](https://img.shields.io/github/license/mustafa-zidan/apache-airflow-providers-rabbitmq)](LICENSE)

## Overview

The **Apache Airflow Provider for RabbitMQ** enables seamless integration with RabbitMQ, allowing you to build workflows that publish and consume messages from RabbitMQ queues. This provider includes custom hooks and operators to simplify interactions with RabbitMQ in your Airflow DAGs.

---

## Features

- Publish messages to RabbitMQ exchanges/queues, with AMQP properties (headers, content type, persistence, ...).
- Publish a list of messages over one connection, with per-message routing keys and properties.
- Wait for messages in a queue using an Airflow Sensor, and pass the message to downstream tasks via XCom.
- RabbitMQ connection management via Airflow Connections (URI or host/login/password/port/schema).

---

## Installation

To install the provider, use `pip`:

```bash
pip install apache-airflow-provider-rabbitmq
```

> Note: Supports Python 3.11+ and Apache Airflow 2.8.0+ (including 3.x).  
> **v3.0.0+** uses the `airflow.provider.rabbitmq` namespace, which is what makes the RabbitMQ connection type appear in the UI on Airflow 3.1.7+ (see [Migration](#migration-from-v21x) below).

---

## Migration from v2.1.x

As of **v3.0.0**, the provider namespace has moved from `airflow.providers.rabbitmq` (plural) to `airflow.provider.rabbitmq` (singular). This change is required for Airflow 3.1.7+ to correctly register the RabbitMQ connection type in the UI — Airflow 3 refuses to register connection types for packages living under `airflow.providers.*` that are not part of the official Apache distribution.

Update your DAG imports:

```python
# Before (≤ v2.1.x)
from airflow.providers.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator
from airflow.providers.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor
from airflow.providers.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook

# After (v3.0.0+)
from airflow.provider.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
```

> Backward-compatibility shims are in place under `airflow.providers.rabbitmq.*` so old imports keep working, but migrating to the new namespace is strongly recommended.

---

## Configuration

### Add a RabbitMQ Connection in Airflow

1. Navigate to **Admin > Connections** in the Airflow UI.
2. Click on **Create** to add a new connection.
3. Configure the following fields:
    - **Conn Id**: `rabbitmq_default` (or a custom ID)
    - **Conn Type**: `RabbitMQ` (conn type key: `rabbitmq`)
    - **Host**: `<RabbitMQ server hostname or IP>`
    - **Login**: `<RabbitMQ username>`
    - **Password**: `<RabbitMQ password>`
    - **Port**: `5672` (default RabbitMQ port)
    - **Schema**: `<vhost>` (optional; maps to RabbitMQ virtual host)
    - **Extras (JSON)**: Optionally provide `{ "connection_uri": "amqp://user:pass@host:5672/vhost" }` to override the URI. Set `"ssl": true` and the `ssl_*` extras to connect over TLS, see [TLS](docs/usage.md#tls).

You can now reference this connection in your DAGs using the connection ID.

---

## Usage

### Example: Publish a message (Operator)

```python
from airflow import DAG
from datetime import datetime
from airflow.provider.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator

with DAG(
    dag_id="example_rabbitmq_producer",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
):
    publish_message = RabbitMQProducerOperator(
        task_id="publish_message",
        message="Hello, RabbitMQ!",
        exchange="amq.direct",
        routing_key="example",
        conn_id="rabbitmq_default",
        properties={"content_type": "text/plain", "delivery_mode": 2},
        # use_async=True,
    )
```

### Example: Wait for a message (Sensor)

```python
from airflow import DAG
from datetime import datetime
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

with DAG(
    dag_id="example_rabbitmq_sensor",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
):
    wait_for_message = RabbitMQSensor(
        task_id="wait_for_message",
        queue_name="example_queue",
        conn_id="rabbitmq_default",
        deserialize="json",
        poke_interval=30,
        timeout=10 * 60,
    )
```

The sensor pushes the message to XCom, so a downstream task can read it with `ti.xcom_pull(task_ids="wait_for_message")["body"]`. See [usage](docs/usage.md#rabbitmqsensor) for the full shape.

---

## Development

### Prerequisites

- Python 3.11 or later
- Apache Airflow 2.8.0 or later
- Docker (required for integration tests)
- RabbitMQ server (optional, integration tests use Docker)

### Setting Up for Development

1. Clone the repository:
   ```bash
   git clone https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq.git
   cd apache-airflow-providers-rabbitmq
   ```

2. Install the library in editable mode:
   ```bash
   uv sync
   ```

3. Install development dependencies:
   ```bash
   uv sync --extras development
   ```

### Running Tests

This provider uses `pytest` for testing. We recommend using `uv` to manage your environment and run tests.

Run all tests:
```bash
uv run pytest
```

Run unit tests only:
```bash
uv run pytest tests/unit/
```

Run integration tests only (requires Docker):
```bash
uv run pytest tests/integration/
```

### Multi-version Testing with Tox

To test across multiple Python and Airflow versions locally, you can use `tox` directly (it is included in the development dependencies).

#### Python version management

Tox needs the target Python interpreters to be available on your `PATH`. Use [pyenv](https://github.com/pyenv/pyenv) (macOS/Linux) or [pyenv-win](https://github.com/pyenv-win/pyenv-win) (Windows) to install and manage multiple Python versions:

```bash
# Install pyenv (macOS via Homebrew)
brew install pyenv

# Install the required Python versions
pyenv install 3.11 3.12

# Make all versions available in the project directory
pyenv local 3.11 3.12
```

#### Running tox

```bash
# Run unit tests for all supported Python × Airflow combinations
uv run tox

# Run unit tests for a specific environment (Python 3.12 + Airflow 2.10)
uv run tox -e py312-airflow210

# Run integration tests for Airflow 2.10 (requires Docker)
uv run tox -e py312-airflow210-integration

# Run integration tests for Airflow 3.1 (requires Docker)
uv run tox -e py312-airflow31-integration
```

**Unit test environments:** `py{311,312}-airflow{28,29,210,30,31}`

**Integration test environments** (require Docker): `py312-airflow{210,31}-integration`

### Linting, Typing and Formatting

Formatting (black, isort), linting (flake8) and type checking (mypy) run as pre-commit hooks. Install them once:

```bash
uv run pre-commit install
```

To run every check on the whole repository, the same way CI does:

```bash
uv run pre-commit run --all-files
```

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, commit conventions and what a pull request needs. Security issues go through [SECURITY.md](SECURITY.md).

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).

---

## Support

If you encounter any issues, please open an issue on [GitHub](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues).
