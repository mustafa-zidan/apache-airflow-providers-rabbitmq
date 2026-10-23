"""Outgoing messages: what the producer operator and the hook accept and publish."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Union

from airflow.provider.rabbitmq.messages.properties import check_property_names

Body = Union[str, bytes]
Properties = Mapping[str, Any]
# A batch item is a body, or a mapping with "body" (or "message") and optional
# "exchange", "routing_key" and "properties" overrides.
BatchItem = Union[str, bytes, Mapping[str, Any]]


@dataclass(frozen=True)
class OutgoingMessage:
    """One message ready to publish, with the batch defaults already applied."""

    body: Body
    exchange: str
    routing_key: str
    properties: Optional[Properties] = None

    @property
    def body_bytes(self) -> bytes:
        """The body as bytes; a str is UTF-8 encoded."""
        return to_bytes(self.body)


def to_bytes(message: Body) -> bytes:
    """Return the message body as bytes; a str is UTF-8 encoded."""
    return message if isinstance(message, bytes) else message.encode()


def _override(item: Mapping[str, Any], key: str, default: Any) -> Any:
    """Return item[key], or the default when it is missing or None."""
    value = item.get(key)
    return default if value is None else value


def normalize_batch_item(
    item: BatchItem,
    default_exchange: str,
    default_routing_key: str,
    default_properties: Optional[Properties],
) -> OutgoingMessage:
    """
    Turn a batch item into an OutgoingMessage.

    A str or bytes item is the body. A mapping item holds ``body`` (or ``message``)
    and optional ``exchange``, ``routing_key`` and ``properties``; missing or None
    values fall back to the defaults.

    :raises: ValueError if a mapping item has neither 'body' nor 'message'.
    :raises: TypeError if the item or its body is of an unsupported type.
    """
    if isinstance(item, (str, bytes)):
        return OutgoingMessage(
            item, default_exchange, default_routing_key, default_properties
        )
    if isinstance(item, Mapping):
        if "body" in item:
            body = item["body"]
        elif "message" in item:
            body = item["message"]
        else:
            raise ValueError(
                f"Batch item dict must contain 'body' or 'message': {item}"
            )
        if not isinstance(body, (str, bytes)):
            raise TypeError(
                f"Message body must be str or bytes, got {type(body).__name__}"
            )
        return OutgoingMessage(
            body,
            _override(item, "exchange", default_exchange),
            _override(item, "routing_key", default_routing_key),
            _override(item, "properties", default_properties),
        )
    raise TypeError(
        f"Batch item must be str, bytes, or dict, got {type(item).__name__}"
    )


def normalize_batch(
    items: Sequence[BatchItem],
    default_exchange: str,
    default_routing_key: str,
    default_properties: Optional[Properties],
) -> list[OutgoingMessage]:
    """Normalize every item of a batch, see ``normalize_batch_item``."""
    return [
        normalize_batch_item(
            item, default_exchange, default_routing_key, default_properties
        )
        for item in items
    ]


def check_message_property_names(
    message: Union[Body, Sequence[BatchItem]],
    properties: Optional[Properties],
) -> None:
    """
    Check the property names of a message argument and of each batch item.

    Only names are checked: values can still be unrendered templates.

    :raises: ValueError on an unknown property name or a mapping item without body.
    :raises: TypeError if a batch item or its body is of an unsupported type.
    """
    check_property_names(properties)
    if isinstance(message, (list, tuple)):
        for outgoing in normalize_batch(message, "", "", None):
            check_property_names(outgoing.properties)
