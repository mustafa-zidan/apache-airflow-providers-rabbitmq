# Apache Airflow Provider for RabbitMQ - Release Notes

## Version 5.1.0 (2026-10-26)

### Breaking Changes
- `RabbitMQHook` no longer takes `connection_uri`. Every hook, operator, sensor and trigger connects through `conn_id`. To use a raw URI, put it in the connection's Extra field as `{"connection_uri": "amqp://..."}`, or define the connection with an `AIRFLOW_CONN_<CONN_ID>` environment variable. The read-only `connection_uri` property still returns the URI built from the connection.

### Migration Guide
```python
# Before
hook = RabbitMQHook(connection_uri="amqp://user:pass@host:5672/")

# After: create a connection with Extra {"connection_uri": "amqp://user:pass@host:5672/"}
hook = RabbitMQHook(conn_id="my_rabbitmq")
```

### Behaviour Changes
- Publishing waits for the broker to accept each message. `RabbitMQProducerOperator` and `RabbitMQHook` take `confirm` (default `True`), which turns on publisher confirms, and the task fails with `MessageNotDeliveredError` when the broker nacks a message. The async path already used confirms; the sync path didn't, so a sync task that published into a full `reject-publish` queue used to succeed with the message lost, and now fails. Pass `confirm=False` for the old behaviour ([#13](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/13)).
- `RabbitMQHook.get_sync_connection_cm` raises `ConnectionError` only when the connection can't be opened. An error raised inside the `with` block now propagates as itself, so a sync publish to a missing exchange raises pika's `ChannelClosedByBroker` instead of `ConnectionError`. `RabbitMQSensor` now fails the task on a `max_xcom_bytes` or deserialize error, as documented, instead of logging it as a connection error and poking again.

### Features
- `RabbitMQSensor` pushes the message it receives to XCom instead of logging and discarding it. The value is the same dict `RabbitMQTrigger` yields: `body` (UTF-8, or base64), `body_encoding`, `exchange`, `routing_key`, `redelivered`, `content_type`, `message_id`, `correlation_id` and `headers`. `deserialize="json"` parses the body, and `max_xcom_bytes` fails the task rather than storing a large body in the metadata database. The sensor acks only once the payload is built, so a body that fails to parse or is too large stays on the queue, and `auto_ack=False` returns the message and requeues it ([#10](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/10)).
- TLS is configured through the connection's Extra JSON: `ssl`, `ssl_ca_certs`, `ssl_certfile`, `ssl_keyfile`, `ssl_verify` and `ssl_server_hostname`, plus `ssl_ca_cert_pem`, `ssl_cert_pem` and `ssl_key_pem` for certificates kept as PEM contents. Client certificates make mutual TLS work. With `ssl` set, a connection built from Host connects with `amqps` and defaults to port 5671; before, it always used `amqp`. Both the sync and async paths use the same `SSLContext` ([#14](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/14)).
- `mandatory=True` fails the task with `MessageNotDeliveredError` when a message matches no queue, instead of the broker dropping it. It needs `confirm=True`. Errors from pika and aio-pika are mapped onto `MessageNotDeliveredError` (`airflow.provider.rabbitmq.exceptions`), whose `reason` is `"nacked"` or `"unroutable"` ([#13](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/13)).
- `RabbitMQProducerOperator` takes `properties`, a templated dict of AMQP basic properties (`content_type`, `headers`, `delivery_mode`, `priority`, `correlation_id`, `expiration`, ...). `publish_sync` and `publish_async` take the same argument and convert it for pika and aio-pika, so `expiration` is milliseconds on both paths. Unknown keys and invalid values raise `ValueError` before connecting. `message` also accepts `bytes` ([#11](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/11)).
- `RabbitMQProducerOperator` publishes a list of messages in order over one connection and channel, and returns how many it published. Items are `str`, `bytes`, or dicts with `body` and optional `routing_key`, `exchange` and `properties` overrides; item properties merge over the operator's. Every item is validated before connecting, and an empty list publishes nothing. `RabbitMQHook` has `publish_batch_sync` and `publish_batch_async` for the same ([#12](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/12)).

## Version 5.0.1 (2026-10-14)

### Bug Fixes
- `RabbitMQTrigger` yields the return value of `apply_function` as the event payload, as Kafka's `AwaitMessageTrigger` does. A falsy return still skips the message, and `True` still yields the standard payload ([#27](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/27)).
- `RabbitMQTrigger` unwraps kwargs that Airflow before 3.3.1 passes to `AssetWatcher` triggers still serialization-wrapped (`{"Encoding.VAR": ..., "Encoding.TYPE": "dict"}`), which declared queues with the wrong arguments ([#28](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/28), apache/airflow#65973).

## Version 5.0.0 (2026-10-13)

### Breaking Changes
- `RabbitMQSensor` takes `queue_name` instead of `queue`. `queue` is a `BaseOperator` argument (the executor queue), and the sensor was overwriting it. `queue` now means the executor queue again.
- Removed the `async` extra. It pinned `aio-pika<10`, while aio-pika 10.1+ is already a required dependency. Install `apache-airflow-provider-rabbitmq` without `[async]`.

### Migration Guide
```python
# Before
RabbitMQSensor(task_id="wait", queue="my_queue", conn_id="rabbitmq_default")

# After
RabbitMQSensor(task_id="wait", queue_name="my_queue", conn_id="rabbitmq_default")
```

### Features
- `RabbitMQTrigger` (`airflow.provider.rabbitmq.triggers.rabbitmq_trigger`) consumes from a queue or an exchange binding and yields a JSON-safe event with the body, exchange, routing key, properties and headers. It works with `AssetWatcher` on Airflow 3.0+ ([#24](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/pull/24)). It takes `conn_id`; put a raw URI in the connection's Extra field. `apply_function` filters messages, and a message that fails twice is rejected instead of requeued.
- The connection form shows placeholders for host, port and vhost ([#23](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/23)).

### Bug Fixes
- `publish_async` now publishes to the named exchange instead of always using the default exchange, and fails the task when that exchange doesn't exist ([#6](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/6)).
- Login, password and vhost are percent-encoded in the connection URI. A password containing `/`, `#` or `?`, the default vhost `/`, and a login with an empty password now all connect correctly ([#7](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/7)).
- `provider.yaml` registers the trigger and matches `get_provider_info()` on name, description and integrations ([#9](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/9)).

### Documentation
- Supported versions are stated as Airflow 2.8.0+ everywhere. The 3.1.7 note is about the connection type showing up in the UI, not a minimum version.
- Added `docs/examples/local-airflow`, a Podman pod with Airflow 3.3, RabbitMQ and Postgres for trying the provider locally.

### Maintenance
- CI runs Airflow 3.2 and 3.3 on Python 3.13 and 3.14.
- A metadata test checks that `provider.yaml` and `get_provider_info()` agree on every key they share.

---

## Version 4.1.0 (2026-10-05)

### Bug Fixes
- Restored the missing `3.0.0` and `3.0.1` entries in the `provider.yaml` versions list ([#8](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/8)).
- `__version__` in `airflow.provider.rabbitmq` and the legacy `airflow.providers.rabbitmq` namespace now reports the package version instead of the stale `0.1.0` / `2.0.0`.

### Maintenance
- Added metadata tests that check `provider.yaml` lists every released version and matches the `pyproject.toml` version.

---

## Version 4.0.0 (2026-10-05)

### Breaking Changes
- Python 3.11 or later is now required (aio-pika 10 dropped Python 3.10).
- `RabbitMQProducerOperator` and `RabbitMQSensor` no longer accept `connection_uri`. Put the URI in the Airflow connection's Extra field instead: `{"connection_uri": "amqp://user:pass@host:5672/vhost"}`, and pass `conn_id`. `RabbitMQHook` still accepts `connection_uri`.
- `RabbitMQSensor.poke` now catches only `ConnectionError` and pika `AMQPError`. Other exceptions propagate and fail the task instead of being logged and treated as "no message".

### Migration Guide
```python
# Before
RabbitMQSensor(task_id="wait", queue="q", connection_uri="amqp://user:pass@host:5672/")

# After: create a connection with Extra {"connection_uri": "amqp://user:pass@host:5672/"}
RabbitMQSensor(task_id="wait", queue="q", conn_id="my_rabbitmq")
```

### Maintenance
- Dependencies updated to their latest versions: aio-pika 10, pika 1.4.4, testcontainers 4.15, and dev tooling (pytest 9, pytest-asyncio 1, pytest-cov 7, pylint 4, black 26, isort 9, mypy 2, tox, tox-uv).
- Pylint now passes with 10/10 and no relaxed limits.

---

## Version 3.0.1 (2026-10-05)

### Maintenance
- Refreshed `uv.lock` to the latest compatible dependency versions.
- Fixed mypy `no-redef` errors on the `Context` fallback import in the producer operator and sensor (type-checking only, no runtime change).

---

## Version 3.0.0 (2026-08-18)

### Breaking Changes
- The provider namespace has moved from `airflow.providers.rabbitmq` to `airflow.provider.rabbitmq` (singular) to comply with Airflow 3.1.7 provider-discovery requirements. Airflow 3 rejects connection-type registration for packages that live under `airflow.providers.*` and are not part of the official Apache distribution. This namespace change is backward-incompatible and therefore ships as a major release.
- The entry point `apache_airflow_provider` now points to `airflow.provider.rabbitmq.get_provider_info:get_provider_info`.

### Migration Guide
Update your DAG imports:

```python
# Before
from airflow.providers.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator
from airflow.providers.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor
from airflow.providers.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook

# After
from airflow.provider.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
```

Backward-compatibility shims are provided in the old `airflow.providers.rabbitmq.*` namespace so existing code continues to import without errors, but you should migrate to the new namespace at your earliest convenience.

### Enhancements
- RabbitMQ connection type is now correctly registered in the Airflow 3.1.7 UI (Admin > Connections > Connection Type dropdown).

---

## Version 2.1.1 (2026-06-07)

### Bug Fixes
- Add provider entrypoint and `get_provider_info` function so the package is discovered correctly by Airflow (#2).
- Make the RabbitMQ test queue durable to prevent flaky integration tests.

### Maintenance
- Update GitHub Actions workflow dependencies to latest versions.
- Fix formatting issues.

---

## Version 2.1.0 (2026-02-21)

### Enhancements
- Improve RabbitMQ integration tests: migrate to pytest + testcontainers, use async mock in unit tests, and refactor test class variables.
- Update provider docs with usage guide, connection setup examples, and known limitations.

### Bug Fixes
- Remove unnecessary connection close in RabbitMQ hook to prevent double-close errors.
- Fix type hints across hook and operator modules.

### Maintenance
- Fix CI configuration for tox-based testing.
- Fix linting issues across the codebase.
- Add `.aiignore` file.

---

## Version 2.0.0 (2025-11-05)

This is a major release that adds compatibility with Apache Airflow 3.x and drops support for 2.x.

### Breaking changes
- Requires Apache Airflow >= 3.0.0
- Import paths updated to the new Airflow 3 SDK layout:
  - BaseHook: `airflow.hooks.base.BaseHook` → `airflow.sdk.bases.hook.BaseHook`
  - BaseSensorOperator/PokeReturnValue: `airflow.sensors.base` → `airflow.sdk.bases.sensor`
  - Context: `airflow.utils.context.Context` → `airflow.sdk.definitions.context.Context`

### Enhancements
- Align the provider with Airflow 3 SDK modules and typing.

### Maintenance
- Bump provider version to `2.0.0`
- Update dependency constraint in `pyproject.toml` to `apache-airflow>=3.0.0`
- Refresh dependency lockfile (`uv.lock`)

### Migration guide
- Update any direct imports in your DAGs/custom code:
  - `from airflow.hooks.base import BaseHook` → `from airflow.sdk.bases.hook import BaseHook`
  - `from airflow.sensors.base import BaseSensorOperator, PokeReturnValue` → `from airflow.sdk.bases.sensor import BaseSensorOperator, PokeReturnValue`
  - `from airflow.utils.context import Context` → `from airflow.sdk.definitions.context import Context`
- Ensure your environment is running Apache Airflow 3.x before upgrading this provider.


## Version 1.0.0 (Initial Release)

We're excited to announce the initial release of the Apache Airflow Provider for RabbitMQ! This provider package enables seamless integration between Apache Airflow and RabbitMQ messaging system.

### Key Features

- **RabbitMQHook**: Core component for connecting to RabbitMQ
  - Supports both synchronous (via `pika`) and asynchronous (via `aio-pika`) messaging
  - Flexible connection configuration through Airflow connections or direct URIs
  - Comprehensive error handling and logging

- **RabbitMQProducerOperator**: Publish messages to RabbitMQ from your DAGs
  - Support for both synchronous and asynchronous publishing
  - Integration with Airflow's templating system
  - Clean interface with sensible defaults

- **RabbitMQSensor**: Monitor RabbitMQ queues within your workflows
  - Configurable message acknowledgment
  - Seamless integration with Airflow's sensor framework

### Installation

```bash
pip install apache-airflow-provider-rabbitmq
```

### Requirements

- Python 3.12 or later
- Apache Airflow 2.0.0 or later
- pika 1.3.0 or later (for synchronous messaging)
- aio-pika 9.5.0 or later (for asynchronous messaging)

### Usage Examples

#### Publishing a Message to RabbitMQ

```python
from airflow import DAG
from airflow.provider.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2023, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG('rabbitmq_example', default_args=default_args, schedule_interval=timedelta(days=1)) as dag:
    # Synchronous message publishing
    publish_task = RabbitMQProducerOperator(
        task_id='publish_to_rabbitmq',
        connection_uri='amqp://guest:guest@rabbitmq:5672/',
        message='{"data": "example message", "timestamp": "{{ ts }}"}',
        exchange='',
        routing_key='my_queue',
        use_async=False,
    )

    # Asynchronous message publishing
    publish_async_task = RabbitMQProducerOperator(
        task_id='publish_to_rabbitmq_async',
        connection_uri='amqp://guest:guest@rabbitmq:5672/',
        message='{"data": "async example message", "timestamp": "{{ ts }}"}',
        exchange='',
        routing_key='my_queue',
        use_async=True,
    )
```

#### Monitoring a RabbitMQ Queue

```python
from airflow import DAG
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor
from datetime import datetime, timedelta

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2023, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG('rabbitmq_sensor_example', default_args=default_args, schedule_interval=timedelta(days=1)) as dag:
    # Wait for a message in the queue
    wait_for_message = RabbitMQSensor(
        task_id='wait_for_rabbitmq_message',
        connection_uri='amqp://guest:guest@rabbitmq:5672/',
        queue='my_queue',
        poke_interval=30,  # Check every 30 seconds
        timeout=60 * 10,   # Timeout after 10 minutes
        mode='poke',
    )
```

### Configuring Connections

You can configure RabbitMQ connections in Airflow's UI:

1. Navigate to Admin > Connections
2. Add a new connection
3. Set the Connection Type to "RabbitMQ"
4. Fill in the Host, Port, Login, Password, and optionally the Virtual Host (in Schema field)
5. Alternatively, you can provide a connection URI in the Extra field:
   ```json
   {
     "connection_uri": "amqp://guest:guest@rabbitmq:5672/vhost"
   }
   ```

### Future Improvements

We're planning to enhance this provider with additional features in future releases:
- Asynchronous sensor for RabbitMQ
- Message serialization/deserialization support
- Queue and exchange declaration operators
- Consumer operator for processing messages from RabbitMQ
- Enhanced monitoring and metrics

### Feedback and Contributions

We welcome feedback and contributions! Please submit issues and pull requests to our GitHub repository.
