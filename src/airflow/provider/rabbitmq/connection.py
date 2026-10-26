"""Build the AMQP URI the hook connects with from an Airflow connection."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

from airflow.provider.rabbitmq.tls import uses_tls


def quote_component(value: Optional[str]) -> str:
    """Percent-encode a URI component, including '/'."""
    return quote(value or "", safe="")


def build_connection_uri(conn: Any) -> Optional[str]:
    """
    Return the AMQP URI for an Airflow connection, or None if it has none.

    Host and port take precedence over a ``connection_uri`` in the extras. Login,
    password and vhost are percent-encoded so characters like @, / and # stay part
    of the value. The colon is kept when the password is empty: pika fails on a
    login with no password part.

    With the ``ssl`` extra the scheme is ``amqps`` and the port defaults to 5671.

    :raises: ValueError if ``ssl`` is set and the ``connection_uri`` extra isn't amqps.
    """
    tls = uses_tls(conn.extra_dejson)
    port = conn.port or (5671 if tls else None)
    if conn.host and port:
        user_pass = ""
        if conn.login or conn.password:
            user_pass = (
                f"{quote_component(conn.login)}:{quote_component(conn.password)}@"
            )

        vhost = f"/{quote_component(conn.schema)}" if conn.schema else ""
        scheme = "amqps" if tls else "amqp"

        return f"{scheme}://{user_pass}{conn.host}:{port}{vhost}"

    uri = conn.extra_dejson.get("connection_uri")
    if uri and tls and not str(uri).startswith("amqps://"):
        raise ValueError("The ssl extra needs an amqps:// connection_uri")
    return str(uri) if uri else None
