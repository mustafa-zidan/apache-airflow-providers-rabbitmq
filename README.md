# Apache Airflow Provider for RabbitMQ

[![PyPI version](https://badge.fury.io/py/apache-airflow-provider-rabbitmq.svg?icon=si%3Apython)](https://badge.fury.io/py/apache-airflow-provider-rabbitmq)
[![License](https://img.shields.io/github/license/mustafa-zidan/apache-airflow-providers-rabbitmq)](LICENSE)

## Overview

The **Apache Airflow Provider for RabbitMQ** enables seamless integration with RabbitMQ, allowing you to build workflows that publish and consume messages from RabbitMQ queues. This provider includes custom hooks and operators to simplify interactions with RabbitMQ in your Airflow DAGs.

---

## Features

- Publish messages to RabbitMQ exchanges/queues.
- Wait for messages in a queue using an Airflow Sensor.
- RabbitMQ connection management via Airflow Connections (URI or host/login/password/port/schema).

---

## Installation

To install the provider, use `pip`:

```bash
pip install apache-airflow-provider-rabbitmq
```

> Note: Requires Python 3.12+ and Apache Airflow 3.0 or later.

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
    - **Extras (JSON)**: Optionally provide `{ "connection_uri": "amqp://user:pass@host:5672/vhost" }` to override the URI.

You can now reference this connection in your DAGs using the connection ID.

---

## Usage

### Example: Publish a message (Operator)

```python
from airflow import DAG
from datetime import datetime
from airflow.providers.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator

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
        # use_async=True,
    )
```

### Example: Wait for a message (Sensor)

```python
from airflow import DAG
from datetime import datetime
from airflow.providers.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

with DAG(
    dag_id="example_rabbitmq_sensor",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
):
    wait_for_message = RabbitMQSensor(
        task_id="wait_for_message",
        queue="example_queue",
        conn_id="rabbitmq_default",
        poke_interval=30,
        timeout=10 * 60,
    )
```

---

## Development

### Prerequisites

- Python 3.12 or later
- Apache Airflow 3.0 or later
- RabbitMQ server (local or remote)

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

This provider uses `pytest` for testing.

Run all tests:
```bash
pytest
```

Run unit tests only:
```bash
pytest tests/unit/
```

Run integration tests only:
```bash
pytest tests/integration/
```

Run tests with coverage:
```bash
pytest --cov=airflow.providers.rabbitmq
```

Run tests with coverage and generate HTML report:
```bash
pytest --cov=airflow.providers.rabbitmq --cov-report=html
```

Run a specific test file:
```bash
pytest tests/unit/hooks/test_rabbitmq_hook.py
```

Run a specific test:
```bash
pytest tests/unit/hooks/test_rabbitmq_hook.py::TestRabbitMQHook::test_init
```

For more information about testing, see the [tests README](tests/README.md).

### Linting and Formatting

This project uses `pylint` for linting.

Run the linter:
```bash
pylint src/ tests/
```

### Contributing

We welcome contributions to the project! To contribute:

1. Fork the repository.
2. Create a feature branch:
   ```bash
   git checkout -b my-feature-branch
   ```
3. Make changes and commit them:
   ```bash
   git commit -m "Add my new feature"
   ```
4. Push the branch to your fork:
   ```bash
   git push origin my-feature-branch
   ```
5. Open a pull request on the main repository.

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).

---

## Support

If you encounter any issues, please open an issue on [GitHub](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues).
