# Limitations: Apache Airflow RabbitMQ Provider

The RabbitMQ provider for Apache Airflow has some limitations and considerations to keep in mind.

## Synchronous vs. Asynchronous

The `RabbitMQProducerOperator` supports both synchronous and asynchronous message publishing.

- **Synchronous**: Uses the `pika` library. This is the default. It's more straightforward but blocks until the message is sent.
- **Asynchronous**: Uses the `aio-pika` library. This can be more efficient in certain scenarios, but it's executed using `asyncio.run()`, which may have overhead for single messages.

## Sensor Behavior

The `RabbitMQSensor` uses the synchronous `pika` library for polling the queue.

- **Message Consumption**: By default, `auto_ack=True`, meaning the sensor will consume and acknowledge the message from the queue when it's found. This means the message will be removed from the queue. If you want the message to remain in the queue for another process, you should set `auto_ack=False`.
- **Performance**: The sensor performs a single `basic_get` operation on each poke. It does not maintain a long-lived connection or use a consumer (`basic_consume`).

## Message Size and Complexity

- **Body Only**: Currently, the `RabbitMQProducerOperator` and `RabbitMQHook` only support sending string/bytes messages. Advanced features like setting message headers or properties are not yet exposed as operator parameters.
- **Serialization**: It is the user's responsibility to serialize complex data types (e.g., to JSON) before sending them as a message.

## Security

- **TLS/SSL**: The current implementation handles TLS if provided in the `connection_uri` (e.g., `amqps://`), but additional TLS configuration (like client certificates) is not yet explicitly supported in the Airflow connection extras.

## Airflow Version

- This provider is designed for **Airflow 3.0+** and may not be compatible with older versions.
