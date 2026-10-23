"""
Message rules that don't depend on a RabbitMQ client library.

- ``properties``: AMQP basic property names and value validation.
- ``outgoing``: batch items and the OutgoingMessage the hook publishes.
- ``incoming``: the payload the sensor and the trigger hand to Airflow.
"""

from airflow.provider.rabbitmq.messages.incoming import (
    DESERIALIZERS,
    check_deserialize,
    message_payload,
)
from airflow.provider.rabbitmq.messages.outgoing import (
    BatchItem,
    Body,
    OutgoingMessage,
    Properties,
    check_message_property_names,
    normalize_batch,
    normalize_batch_item,
    to_bytes,
)
from airflow.provider.rabbitmq.messages.properties import (
    MESSAGE_PROPERTIES,
    check_property_names,
    normalize_properties,
)

__all__ = [
    "DESERIALIZERS",
    "MESSAGE_PROPERTIES",
    "BatchItem",
    "Body",
    "OutgoingMessage",
    "Properties",
    "check_deserialize",
    "check_message_property_names",
    "check_property_names",
    "message_payload",
    "normalize_batch",
    "normalize_batch_item",
    "normalize_properties",
    "to_bytes",
]
