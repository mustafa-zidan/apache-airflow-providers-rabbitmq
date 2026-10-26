# Usage Guide: Apache Airflow RabbitMQ Provider

The RabbitMQ provider for Apache Airflow allows you to interact with RabbitMQ for publishing messages and sensing for messages in queues.

## Installation

```bash
pip install apache-airflow-provider-rabbitmq
```

## Connection Configuration

To use the RabbitMQ provider, you need to configure a connection in Airflow.

### Using Airflow Connection UI

1. Go to **Admin** -> **Connections**.
2. Click the **+** sign to add a new connection.
3. Set **Connection Id** to `rabbitmq_default` (or your preferred ID).
4. Set **Connection Type** to `RabbitMQ`.
5. Fill in the following fields:
    - **Host**: Your RabbitMQ host.
    - **Port**: Your RabbitMQ port (default is 5672).
    - **Login**: Your RabbitMQ username.
    - **Password**: Your RabbitMQ password.
    - **Schema**: Your RabbitMQ virtual host (vhost).
6. Alternatively, you can provide a `connection_uri` in the **Extra** field:
    ```json
    {
      "connection_uri": "amqp://user:password@host:port/vhost"
    }
    ```

### TLS

Set `"ssl": true` in the **Extra** field to connect over TLS. With Host set, the hook connects with `amqps` and the port defaults to 5671. A `connection_uri` extra must use `amqps://`.

```json
{
  "ssl": true,
  "ssl_ca_certs": "/opt/airflow/certs/ca.pem",
  "ssl_certfile": "/opt/airflow/certs/client.pem",
  "ssl_keyfile": "/opt/airflow/certs/client.key",
  "ssl_server_hostname": "rabbit.internal"
}
```

- `ssl_ca_certs`: CA certificate file the broker certificate is verified against. Without it, the system CAs are trusted.
- `ssl_certfile`, `ssl_keyfile`: client certificate and key, for brokers that require mutual TLS.
- `ssl_ca_cert_pem`, `ssl_cert_pem`, `ssl_key_pem`: the same as PEM contents instead of file paths, for certificates kept in a secrets backend. Each can replace its file counterpart on its own.
- `ssl_server_hostname`: the name the broker certificate must match, when it differs from Host (for example when connecting by IP or through a tunnel).
- `ssl_verify`: defaults to `true`. `false` skips verifying the broker certificate and logs a warning on every connection; use it only for testing.

`ssl` and `ssl_verify` must be JSON booleans. A string like `"true"` or `"yes"` raises `ValueError` rather than being guessed at.

## Operators

### RabbitMQProducerOperator

The `RabbitMQProducerOperator` is used to publish messages to a RabbitMQ exchange.

#### Parameters

- `message`: The message to be sent, as `str` (UTF-8 encoded) or `bytes`, or a list of messages, see [Batches](#batches). (Templated)
- `exchange`: The name of the RabbitMQ exchange. (Templated)
- `routing_key`: The routing key for the message. (Templated)
- `conn_id`: (Optional) Airflow connection ID. Default is `rabbitmq_default`. To use a raw URI, set `connection_uri` in the connection's Extra field.
- `use_async`: (Optional) Boolean flag to use asynchronous publishing via `aio-pika`. Default is `False`.
- `properties`: (Optional) AMQP basic properties for the message, as a dict. (Templated) Unknown keys raise `ValueError` when the DAG is parsed; values are checked after rendering, before connecting.
- `confirm`: (Optional) Wait for the broker to ack each message, and fail the task when it doesn't, see [Delivery checks](#delivery-checks). Default is `True`.
- `mandatory`: (Optional) Also fail the task when a message matches no queue. Needs `confirm`. Default is `False`.

#### Message properties

| Key | Value |
|---|---|
| `content_type`, `content_encoding` | str |
| `headers` | dict, used by headers exchanges for routing |
| `delivery_mode` | `1` transient (the broker default) or `2` persistent |
| `priority` | 0-255; the queue needs `x-max-priority` |
| `correlation_id`, `reply_to`, `message_id`, `type`, `user_id`, `app_id` | str |
| `expiration` | milliseconds, as int, numeric string or `timedelta` |
| `timestamp` | seconds since the epoch, or a `datetime` |

Values may be strings, so `"{{ params.priority }}"` works. Both `use_async` paths take the same keys and units; the hook converts them for `pika` and `aio-pika`. A message survives a broker restart only with `delivery_mode: 2` on a durable queue.

#### Batches

When `message` is a list or tuple, the operator publishes every item in order over one connection and one channel, and returns the number of messages published (pushed to XCom). An item is a `str`, `bytes`, or a dict:

```python
{"body": ..., "routing_key": ..., "exchange": ..., "properties": {...}}
```

`body` (or `message`) is required. A missing or `None` `routing_key` or `exchange` falls back to the operator's value. Item `properties` are merged over the operator's `properties` key by key, so an item can set `priority` and keep the operator's `delivery_mode`; set a key to `None` to unset it for that item. `headers` is replaced, not merged.

Every item is checked before connecting, so a bad item fails the task with nothing sent. An empty list publishes nothing, logs a warning, and succeeds with `0`.

A template renders to a string unless the DAG sets `render_template_as_native_obj=True`. Without it, `"{{ ti.xcom_pull('extract') }}"` publishes one message whose body is `"['a', 'b']"`. Either set the flag on the DAG, or pass the list itself (for example from a `@task` return value) instead of a template.

With `use_async=True` the batch is published sequentially on one channel, the same as the sync path.

```python
with DAG("fan_out", render_template_as_native_obj=True, ...):
    RabbitMQProducerOperator(
        task_id="publish_all",
        message="{{ ti.xcom_pull('extract') }}",  # renders to a list
        exchange="events",
        routing_key="row",
        properties={"delivery_mode": 2},
    )

    RabbitMQProducerOperator(
        task_id="publish_by_type",
        message=[
            {"body": '{"id": 1}', "routing_key": "order"},
            {"body": '{"id": 2}', "routing_key": "refund", "properties": {"priority": 9}},
        ],
        exchange="events",
        routing_key="unknown",
    )
```

#### Delivery checks

With `confirm=True` (the default) the channel uses publisher confirms, on both `use_async` paths. Each publish waits for the broker's ack, and the task fails with `MessageNotDeliveredError` (from `airflow.provider.rabbitmq.exceptions`) when the broker refuses the message: a full queue with `x-overflow=reject-publish`, for example. `reason` on the error is `"nacked"`, and `exchange` and `routing_key` say which message it was.

A message that matches no queue is not refused: the broker acks it and drops it. Set `mandatory=True` to fail the task with `reason="unroutable"` instead. `mandatory` needs `confirm`, because without confirms neither client waits for the broker's reply; `confirm=False, mandatory=True` raises `ValueError` when the DAG is parsed.

`confirm=False` publishes without waiting, which is faster for large batches, and the task succeeds even if the broker drops every message. A missing named exchange still fails the task on both paths.

In a batch the error stops publishing at the refused message. The messages before it are already on the broker.

```python
RabbitMQProducerOperator(
    task_id="publish_order",
    message='{"id": 1}',
    exchange="orders",
    routing_key="created",
    mandatory=True,  # fail if no queue is bound for "created"
)
```

#### Example

```python
from airflow.provider.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator

publish_task = RabbitMQProducerOperator(
    task_id="publish_message",
    message="Hello RabbitMQ!",
    exchange="",
    routing_key="test_queue",
    conn_id="rabbitmq_default",
)

publish_order = RabbitMQProducerOperator(
    task_id="publish_order",
    message="{{ ti.xcom_pull('build_payload') }}",
    exchange="orders",
    routing_key="created",
    properties={
        "content_type": "application/json",
        "delivery_mode": 2,
        "headers": {"source": "airflow", "dag_id": "{{ dag.dag_id }}"},
        "correlation_id": "{{ run_id }}",
        "expiration": "60000",
    },
)
```

## Sensors

### RabbitMQSensor

The `RabbitMQSensor` waits for a message to appear in a RabbitMQ queue and pushes it to XCom.

#### Parameters

- `queue_name`: The name of the RabbitMQ queue to monitor. (Templated)
- `conn_id`: (Optional) Airflow connection ID. Default is `rabbitmq_default`. To use a raw URI, set `connection_uri` in the connection's Extra field.
- `auto_ack`: (Optional) Acknowledge the message, removing it from the queue. Default is `True`. With `False` the sensor peeks: it returns the message and requeues it.
- `deserialize`: (Optional) `None` returns the body as a string, or `"json"` parses it. A body that isn't valid JSON fails the task and stays on the queue. Default is `None`.
- `max_xcom_bytes`: (Optional) Fail the task, leaving the message on the queue, when the body is larger than this. Default is `None` (no limit).

#### XCom value

```python
{
    "body": "...",              # str, base64 str, or the parsed JSON value
    "body_encoding": "utf-8",   # "utf-8", "base64" (body wasn't UTF-8) or "json"
    "exchange": "orders",
    "routing_key": "new",
    "redelivered": False,
    "content_type": "application/json",
    "message_id": "...",
    "correlation_id": "...",
    "headers": {"source": "shop"},  # values converted to str
}
```

`RabbitMQTrigger` yields the same dict as its event payload. When its `apply_function` returns something other than `True`, that return value is the payload instead (as in Kafka's `AwaitMessageTrigger`); a falsy return skips the message. The function is called as `f(*apply_function_args, message, **apply_function_kwargs)`, and its return value must be JSON-serializable.

The value is stored in the Airflow metadata database. If the queue can carry large messages, set `max_xcom_bytes`, or pass a reference (such as an object storage key) in the message instead of the data.

The body is logged at DEBUG only; INFO logs its size and routing key.

#### Example

```python
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

wait_for_message = RabbitMQSensor(
    task_id="wait_for_message",
    queue_name="test_queue",
    deserialize="json",
    poke_interval=30,
    timeout=600,
)

# Downstream: ti.xcom_pull(task_ids="wait_for_message")["body"]["order_id"]
```

## Hooks

### RabbitMQHook

The `RabbitMQHook` provides a low-level interface to RabbitMQ.

```python
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook

hook = RabbitMQHook(conn_id="rabbitmq_default")
hook.publish_sync(message="Sync message", exchange="", routing_key="test_queue")
```

`confirm` and `mandatory` are hook arguments, with the same defaults and errors as the operator, and apply to every publish method.

```python
hook = RabbitMQHook(conn_id="rabbitmq_default", mandatory=True)
hook.publish_batch_sync(["a", "b"], exchange="events", routing_key="row")
```
