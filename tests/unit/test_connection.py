"""Unit tests for building the AMQP URI from an Airflow connection."""

from types import SimpleNamespace

import pytest

from airflow.provider.rabbitmq.connection import build_connection_uri


def _conn(**fields):
    defaults = {
        "host": None,
        "port": None,
        "login": None,
        "password": None,
        "schema": None,
        "extra_dejson": {},
    }
    return SimpleNamespace(**{**defaults, **fields})


@pytest.mark.parametrize(
    "fields,expected",
    [
        (
            {"host": "h", "port": 5672, "login": "u", "password": "p@ss"},
            "amqp://u:p%40ss@h:5672",
        ),
        ({"host": "h", "port": 5672, "login": "u"}, "amqp://u:@h:5672"),
        ({"host": "h", "port": 5672}, "amqp://h:5672"),
        (
            {"host": "h", "port": 5672, "schema": "team/prod"},
            "amqp://h:5672/team%2Fprod",
        ),
        (
            {"host": "h", "port": 5672, "extra_dejson": {"connection_uri": "amqp://x"}},
            "amqp://h:5672",
        ),
        ({"extra_dejson": {"connection_uri": "amqp://x"}}, "amqp://x"),
        ({"host": "h"}, None),
        ({}, None),
    ],
)
def test_build_connection_uri(fields, expected):
    assert build_connection_uri(_conn(**fields)) == expected
