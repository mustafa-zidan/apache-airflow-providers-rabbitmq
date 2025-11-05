# Apache Airflow Provider for RabbitMQ

[![PyPI version](https://badge.fury.io/py/apache-airflow-provider-rabbitmq.svg)](https://badge.fury.io/py/apache-airflow-provider-rabbitmq)
[![License](https://img.shields.io/github/license/mustafa-zidan/apache-airflow-providers-rabbitmq)](LICENSE)

## Overview

The **Apache Airflow Provider for RabbitMQ** enables seamless integration with RabbitMQ, allowing you to build workflows that publish and consume messages from RabbitMQ queues. This provider includes custom hooks and operators to simplify interactions with RabbitMQ in your Airflow DAGs.

---

## Features

- Publish messages to RabbitMQ queues.
- Consume messages from RabbitMQ queues.
- Full support for RabbitMQ connection management in Airflow.

---

## Installation

To install the provider, use `pip`:

```bash
pip install apache-airflow-provider-rabbitmq
```

> **Note**: This provider requires Apache Airflow 2.0 or later.

---

## Configuration

### Add a RabbitMQ Connection in Airflow

1. Navigate to **Admin > Connections** in the Airflow UI.
2. Click on **Create** to add a new connection.
3. Configure the following fields:
    - **Conn Id**: `rabbitmq_default` (or a custom ID)
    - **Conn Type**: `RabbitMQ`
    - **Host**: `<RabbitMQ server hostname or IP>`
    - **Login**: `<RabbitMQ username>`
    - **Password**: `<RabbitMQ password>`
    - **Port**: `5672` (default RabbitMQ port)

You can now reference this connection in your DAGs using the connection ID.

---

## Usage

### Example DAG: Publish and Consume Messages

Here’s an example DAG demonstrating how to use the RabbitMQ operator:

```python
from airflow import DAG
from datetime import datetime
from airflow.providers.rabbitmq.operators.rabbitmq import RabbitMQOperator

def process_message(message):
    print(f"Received message: {message}")

with DAG(
    dag_id="example_rabbitmq_dag",
    default_args={"start_date": datetime(2023, 1, 1)},
    schedule_interval=None,
    catchup=False,
) as dag:

    publish_task = RabbitMQOperator(
        task_id="publish_message",
        rabbitmq_conn_id="rabbitmq_default",
        queue="example_queue",
        message="Hello, RabbitMQ!",
        mode="publish",
    )

    consume_task = RabbitMQOperator(
        task_id="consume_message",
        rabbitmq_conn_id="rabbitmq_default",
        queue="example_queue",
        mode="consume",
        callback=process_message,
    )

    publish_task >> consume_task
```

### Key Features
- **`publish` mode**: Sends messages to a RabbitMQ queue.
- **`consume` mode**: Consumes messages from a RabbitMQ queue and processes them using a callback.

---

## Development

### Prerequisites

- Python 3.12 or later
- Apache Airflow 2.3 or later
- RabbitMQ server (local or remote)

### Setting Up for Development

1. Clone the repository:
   ```bash
   git clone https://github.com/mustafazidan/apache-airflow-provider-rabbitmq.git
   cd apache-airflow-provider-rabbitmq
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

If you encounter any issues, please open an issue on [GitHub](https://github.com/mustafazidan/apache-airflow-provider-rabbitmq/issues).
