# Apache Airflow Provider for RabbitMQ - Release Notes

## Version 1.1.0 (2025-11-05)

### Changes since 1.0.0

- chore: update uv.lock

### Notes

- No functional code changes; dependency lockfile updated.

----

## Version 0.1.0 (Initial Release)

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
from airflow.providers.rabbitmq.operators.rabbitmq_producer import RabbitMQProducerOperator
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
from airflow.providers.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor
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
