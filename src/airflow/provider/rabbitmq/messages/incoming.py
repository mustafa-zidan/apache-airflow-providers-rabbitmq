"""The message payload shared by RabbitMQSensor (XCom) and RabbitMQTrigger (event)."""

from __future__ import annotations

import base64
import json
from typing import Any, Mapping, Optional

DESERIALIZERS = (None, "json")


def check_deserialize(deserialize: Optional[str]) -> None:
    """Raise ValueError if ``deserialize`` isn't one of DESERIALIZERS."""
    if deserialize not in DESERIALIZERS:
        raise ValueError(f"deserialize must be one of {DESERIALIZERS}: {deserialize!r}")


def message_payload(  # pylint: disable=too-many-arguments
    body: bytes,
    *,
    exchange: Optional[str],
    routing_key: Optional[str],
    redelivered: Optional[bool],
    content_type: Optional[str],
    message_id: Optional[str],
    correlation_id: Optional[str],
    headers: Optional[Mapping[str, Any]],
    deserialize: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build the JSON-safe dict Airflow stores for a message.

    The body is decoded as UTF-8, or base64-encoded when it isn't valid UTF-8, and
    ``body_encoding`` says which. With ``deserialize="json"`` a UTF-8 body is parsed
    and ``body_encoding`` is "json"; a body that isn't valid JSON raises ValueError.
    """
    check_deserialize(deserialize)

    body_value: Any
    try:
        body_value, body_encoding = body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        body_value = base64.b64encode(body).decode("ascii")
        body_encoding = "base64"

    if deserialize == "json":
        if body_encoding != "utf-8":
            raise ValueError("deserialize='json' needs a UTF-8 body")
        body_value, body_encoding = json.loads(body_value), "json"

    return {
        "body": body_value,
        "body_encoding": body_encoding,
        "exchange": exchange,
        "routing_key": routing_key,
        "redelivered": redelivered,
        "content_type": content_type,
        "message_id": message_id,
        "correlation_id": correlation_id,
        # Header values can be bytes, Decimal or datetime.
        "headers": {k: str(v) for k, v in (headers or {}).items()},
    }
