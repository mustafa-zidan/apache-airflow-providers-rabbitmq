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

## Operators

### RabbitMQProducerOperator

The `RabbitMQProducerOperator` is used to publish messages to a RabbitMQ exchange.

#### Parameters

- `message`: The message string to be sent. (Templated)
- `exchange`: The name of the RabbitMQ exchange. (Templated)
- `routing_key`: The routing key for the message. (Templated)
- `connection_uri`: (Optional) Direct RabbitMQ connection URI.
- `conn_id`: (Optional) Airflow connection ID. Default is `rabbitmq_default`.
- `use_async`: (Optional) Boolean flag to use asynchronous publishing via `aio-pika`. Default is `False`.

#### Example

```python
from airflow.providers.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator

publish_task = RabbitMQProducerOperator(
    task_id="publish_message",
    message="Hello RabbitMQ!",
    exchange="",
    routing_key="test_queue",
    conn_id="rabbitmq_default",
)
```

## Sensors

### RabbitMQSensor

The `RabbitMQSensor` waits for a message to appear in a RabbitMQ queue.

#### Parameters

- `queue`: The name of the RabbitMQ queue to monitor. (Templated)
- `connection_uri`: (Optional) Direct RabbitMQ connection URI.
- `conn_id`: (Optional) Airflow connection ID. Default is `rabbitmq_default`.
- `auto_ack`: (Optional) Whether to automatically acknowledge the message upon receipt. Default is `True`.

#### Example

```python
from airflow.providers.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

wait_for_message = RabbitMQSensor(
    task_id="wait_for_message",
    queue="test_queue",
    poke_interval=30,
    timeout=600,
)
```

## Hooks

### RabbitMQHook

The `RabbitMQHook` provides a low-level interface to RabbitMQ.

```python
from airflow.providers.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook

hook = RabbitMQHook(conn_id="rabbitmq_default")
hook.publish_sync(message="Sync message", exchange="", routing_key="test_queue")
```
