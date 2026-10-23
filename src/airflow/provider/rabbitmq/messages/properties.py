"""AMQP basic properties: the supported names and their validation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

# AMQP basic properties that both pika and aio-pika accept.
MESSAGE_PROPERTIES = frozenset(
    {
        "content_type",
        "content_encoding",
        "headers",
        "delivery_mode",
        "priority",
        "correlation_id",
        "reply_to",
        "expiration",
        "message_id",
        "timestamp",
        "type",
        "user_id",
        "app_id",
    }
)


def check_property_names(properties: Optional[Mapping[str, Any]]) -> None:
    """Raise ValueError on keys that aren't AMQP basic properties."""
    unknown = sorted(set(properties or {}) - MESSAGE_PROPERTIES)
    if unknown:
        raise ValueError(
            f"Unknown message properties: {', '.join(unknown)}. "
            f"Supported: {', '.join(sorted(MESSAGE_PROPERTIES))}"
        )


def normalize_properties(properties: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """
    Validate message properties and convert them to their AMQP wire form.

    Values may be strings, since templated fields render to strings.
    ``delivery_mode`` is 1 (transient) or 2 (persistent), ``priority`` 0-255,
    ``expiration`` milliseconds (int, numeric string or timedelta) and
    ``timestamp`` seconds since the epoch or a datetime. None values are dropped.

    :return: The properties as pika takes them: ``expiration`` a string of
        milliseconds and ``timestamp`` an int.
    """
    check_property_names(properties)
    props = {k: v for k, v in (properties or {}).items() if v is not None}

    if "delivery_mode" in props:
        props["delivery_mode"] = int(props["delivery_mode"])
        if props["delivery_mode"] not in (1, 2):
            raise ValueError("delivery_mode must be 1 (transient) or 2 (persistent)")
    if "priority" in props:
        props["priority"] = int(props["priority"])
        if not 0 <= props["priority"] <= 255:
            raise ValueError("priority must be between 0 and 255")
    if "expiration" in props:
        expiration = props["expiration"]
        if isinstance(expiration, timedelta):
            milliseconds = int(expiration.total_seconds() * 1000)
        else:
            milliseconds = int(expiration)
        if milliseconds < 0:
            raise ValueError("expiration must not be negative")
        props["expiration"] = str(milliseconds)
    if "timestamp" in props:
        timestamp = props["timestamp"]
        props["timestamp"] = (
            int(timestamp.timestamp())
            if isinstance(timestamp, datetime)
            else int(timestamp)
        )
    if "headers" in props and not isinstance(props["headers"], Mapping):
        raise ValueError("headers must be a dict")
    return props
