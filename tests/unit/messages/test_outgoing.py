"""Unit tests for the outgoing message rules."""

from types import MappingProxyType

import pytest

from airflow.provider.rabbitmq import message, messages
from airflow.provider.rabbitmq.hooks import rabbitmq_hook
from airflow.provider.rabbitmq.messages.outgoing import (
    OutgoingMessage,
    check_message_property_names,
    normalize_batch,
    normalize_batch_item,
    to_bytes,
)

DEFAULTS = ("ex", "key", {"priority": 1})


@pytest.mark.parametrize(
    "item,expected",
    [
        ("text", OutgoingMessage("text", "ex", "key", {"priority": 1})),
        (b"raw", OutgoingMessage(b"raw", "ex", "key", {"priority": 1})),
        ({"body": "b"}, OutgoingMessage("b", "ex", "key", {"priority": 1})),
        ({"message": "m"}, OutgoingMessage("m", "ex", "key", {"priority": 1})),
        (
            {
                "body": "b",
                "exchange": "other",
                "routing_key": "rk",
                "properties": {"priority": 9},
            },
            OutgoingMessage("b", "other", "rk", {"priority": 9}),
        ),
        (
            {"body": "b", "exchange": None, "routing_key": None, "properties": None},
            OutgoingMessage("b", "ex", "key", {"priority": 1}),
        ),
        (
            MappingProxyType({"body": "b"}),
            OutgoingMessage("b", "ex", "key", {"priority": 1}),
        ),
    ],
)
def test_normalize_batch_item_applies_defaults(item, expected):
    assert normalize_batch_item(item, *DEFAULTS) == expected


@pytest.mark.parametrize(
    "default_properties,item_properties,expected",
    [
        (
            {"delivery_mode": 2, "content_type": "application/json"},
            {"priority": 5},
            {"delivery_mode": 2, "content_type": "application/json", "priority": 5},
        ),
        (
            {"delivery_mode": 2, "priority": 1},
            {"priority": 9},
            {"delivery_mode": 2, "priority": 9},
        ),
        ({"delivery_mode": 2}, {}, {"delivery_mode": 2}),
        ({"delivery_mode": 2}, {"delivery_mode": None}, {"delivery_mode": None}),
        (None, {"priority": 5}, {"priority": 5}),
        ({"headers": {"a": 1}}, {"headers": {"b": 2}}, {"headers": {"b": 2}}),
    ],
)
def test_normalize_batch_item_merges_properties_over_defaults(
    default_properties, item_properties, expected
):
    outgoing = normalize_batch_item(
        {"body": "b", "properties": item_properties}, "ex", "key", default_properties
    )

    assert outgoing.properties == expected


def test_normalize_batch_item_does_not_mutate_default_properties():
    defaults = {"delivery_mode": 2}

    normalize_batch_item(
        {"body": "b", "properties": {"priority": 5}}, "ex", "key", defaults
    )

    assert defaults == {"delivery_mode": 2}


@pytest.mark.parametrize(
    "item,error,match",
    [
        ({"routing_key": "rk"}, ValueError, "must contain 'body' or 'message'"),
        ({"body": 1}, TypeError, "Message body must be str or bytes"),
        (1, TypeError, "Batch item must be str, bytes, or dict"),
    ],
)
def test_normalize_batch_item_rejects_invalid_items(item, error, match):
    with pytest.raises(error, match=match):
        normalize_batch_item(item, *DEFAULTS)


def test_normalize_batch_keeps_order():
    batch = normalize_batch(["a", {"body": "b", "routing_key": "rk"}], *DEFAULTS)

    assert [(m.body, m.routing_key) for m in batch] == [("a", "key"), ("b", "rk")]


def test_to_bytes_encodes_str_as_utf8():
    assert to_bytes("é") == "é".encode("utf-8")
    assert to_bytes(b"\xff") == b"\xff"
    assert OutgoingMessage("é", "", "").body_bytes == "é".encode("utf-8")


@pytest.mark.parametrize(
    "message_arg,properties",
    [
        ("text", {"priority": "{{ params.priority }}"}),
        (["a", {"body": "b", "properties": {"delivery_mode": 2}}], None),
    ],
)
def test_check_message_property_names_accepts_known_names(message_arg, properties):
    check_message_property_names(message_arg, properties)


@pytest.mark.parametrize(
    "message_arg,properties",
    [
        ("text", {"persistent": True}),
        (["a", {"body": "b", "properties": {"persistent": True}}], None),
    ],
)
def test_check_message_property_names_rejects_unknown_names(message_arg, properties):
    with pytest.raises(ValueError, match="Unknown message properties: persistent"):
        check_message_property_names(message_arg, properties)


@pytest.mark.parametrize(
    "name", ["MESSAGE_PROPERTIES", "check_property_names", "normalize_properties"]
)
def test_hook_module_re_exports_message_rules(name):
    assert getattr(rabbitmq_hook, name) is getattr(messages, name)


@pytest.mark.parametrize("name", ["DESERIALIZERS", "message_payload"])
def test_message_module_re_exports_incoming_rules(name):
    assert getattr(message, name) is getattr(messages, name)
