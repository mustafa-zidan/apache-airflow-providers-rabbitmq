"""Kept for backward compatibility: use airflow.provider.rabbitmq.messages.incoming."""

from airflow.provider.rabbitmq.messages.incoming import (  # noqa: F401
    DESERIALIZERS,
    message_payload,
)

__all__ = ["DESERIALIZERS", "message_payload"]
