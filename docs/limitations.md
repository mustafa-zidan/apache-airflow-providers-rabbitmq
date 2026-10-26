# Limitations: Apache Airflow RabbitMQ Provider

The RabbitMQ provider for Apache Airflow has some limitations and considerations to keep in mind.

## Synchronous vs. Asynchronous

The `RabbitMQProducerOperator` supports both synchronous and asynchronous message publishing.

- **Synchronous**: Uses the `pika` library. This is the default. It's more straightforward but blocks until the message is sent.
- **Asynchronous**: Uses the `aio-pika` library. This can be more efficient in certain scenarios, but it's executed using `asyncio.run()`, which may have overhead for single messages.

## Batch Delivery

A batch is not atomic. If publishing fails partway through, the messages before the failure are already on the broker, the task fails, and a retry publishes the whole list again. Delivery is at-least-once, so consumers should tolerate duplicates (for example by `message_id`). With `confirm=False` the task also can't tell whether the broker accepted every message, only that they were sent.

## Sensor Behavior

The `RabbitMQSensor` uses the synchronous `pika` library for polling the queue.

- **Message Consumption**: By default, `auto_ack=True`, meaning the sensor will consume and acknowledge the message from the queue when it's found. This means the message will be removed from the queue. If you want the message to remain in the queue for another process, set `auto_ack=False`: the sensor still returns the message, then requeues it. A requeued message can go back to the front of the queue and is marked as redelivered.
- **XCom Size**: The sensor pushes the message to XCom, which lives in the Airflow metadata database. Use `max_xcom_bytes` to fail on large messages instead of storing them.
- **Performance**: The sensor performs a single `basic_get` operation on each poke. It does not maintain a long-lived connection or use a consumer (`basic_consume`).

## Message Size and Complexity

- **Persistence**: Messages are transient unless `properties={"delivery_mode": 2}` is set, so a broker restart loses them even on a durable queue.
- **Serialization**: It is the user's responsibility to serialize complex data types (e.g., to JSON) before sending them as a message.

## Security

- **TLS/SSL**: TLS, including client certificates, is configured through the connection's Extra field, see [TLS](usage.md#tls). The connection form doesn't show these settings as fields yet ([#18](https://github.com/mustafa-zidan/apache-airflow-providers-rabbitmq/issues/18)), so they go in the Extra JSON. A client key protected by a password isn't supported.

## Airflow Version

- This provider supports **Airflow 2.8.0+**, including 3.x. CI tests Airflow 2.8 through 3.3.
- On Airflow 3.1.7+, the RabbitMQ connection type only appears in the UI with the `airflow.provider.rabbitmq` namespace (v3.0.0+).
