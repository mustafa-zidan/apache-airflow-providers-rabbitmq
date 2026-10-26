"""Build the TLS context the hook connects with from an Airflow connection's extras."""

from __future__ import annotations

import logging
import os
import ssl
import tempfile
from typing import Any, Mapping, Optional

log = logging.getLogger(__name__)


def get_flag(extras: Mapping[str, Any], key: str, default: bool) -> bool:
    """
    Read a boolean extra.

    :raises: ValueError if the value is not a JSON boolean, so a typo like "yes"
        can't silently turn TLS or certificate checks off.
    """
    value = extras.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"The {key} extra must be true or false, got {value!r}")
    return value


def uses_tls(extras: Mapping[str, Any]) -> bool:
    """Return whether the connection's ``ssl`` extra turns TLS on."""
    return get_flag(extras, "ssl", False)


class BrokerSSLContext(ssl.SSLContext):
    """
    An SSLContext that can check the broker certificate against a fixed hostname.

    pika and asyncio pass the host they connect to as ``server_hostname``. aio-pika
    has no option to change it, so the override lives on the context both use.
    """

    server_hostname: Optional[str] = None

    def wrap_socket(self, *args: Any, **kwargs: Any) -> Any:
        if self.server_hostname:
            kwargs["server_hostname"] = self.server_hostname
        return super().wrap_socket(*args, **kwargs)

    def wrap_bio(self, *args: Any, **kwargs: Any) -> Any:
        if self.server_hostname:
            kwargs["server_hostname"] = self.server_hostname
        return super().wrap_bio(*args, **kwargs)


def build_ssl_context(extras: Mapping[str, Any]) -> BrokerSSLContext:
    """
    Build the SSLContext for a connection from its extras.

    - ``ssl_ca_certs`` / ``ssl_ca_cert_pem``: CA file path / PEM contents. Without
      either, the system CAs are trusted.
    - ``ssl_certfile`` / ``ssl_cert_pem`` and ``ssl_keyfile`` / ``ssl_key_pem``:
      client certificate and key for mutual TLS, as file paths or PEM contents.
    - ``ssl_verify``: verify the broker certificate. Defaults to true.
    - ``ssl_server_hostname``: the hostname the broker certificate must match,
      instead of the host connected to.

    :raises: ValueError if ``ssl_verify`` isn't a boolean, or a client key is given
        without a certificate.
    """
    context = BrokerSSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cafile, cadata = extras.get("ssl_ca_certs"), extras.get("ssl_ca_cert_pem")
    if cafile or cadata:
        context.load_verify_locations(cafile=cafile, cadata=cadata)
    else:
        context.load_default_certs()

    if not get_flag(extras, "ssl_verify", True):
        log.warning(
            "ssl_verify is false: the RabbitMQ broker certificate is not verified"
        )
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    context.server_hostname = extras.get("ssl_server_hostname")
    load_client_cert(context, extras)
    return context


def load_client_cert(context: ssl.SSLContext, extras: Mapping[str, Any]) -> None:
    """
    Load the client certificate and key, if any, into the context.

    PEM contents are written to a private temporary directory for the duration of
    the load, since ``load_cert_chain`` only reads files.
    """
    cert_pem, key_pem = extras.get("ssl_cert_pem"), extras.get("ssl_key_pem")
    if not (extras.get("ssl_certfile") or cert_pem):
        if extras.get("ssl_keyfile") or key_pem:
            raise ValueError("A TLS client key needs ssl_certfile or ssl_cert_pem")
        return

    with tempfile.TemporaryDirectory() as tmp:
        context.load_cert_chain(
            (
                write_pem(tmp, "cert.pem", cert_pem)
                if cert_pem
                else extras["ssl_certfile"]
            ),
            (
                write_pem(tmp, "key.pem", key_pem)
                if key_pem
                else extras.get("ssl_keyfile")
            ),
        )


def write_pem(directory: str, name: str, contents: str) -> str:
    """Write PEM contents to a file in a directory only its owner can read."""
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(contents)
    return path
