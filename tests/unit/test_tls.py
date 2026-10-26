"""Unit tests for building the TLS context from connection extras."""

import logging
import ssl
from unittest import mock

import pytest
import trustme

from airflow.provider.rabbitmq.tls import BrokerSSLContext, build_ssl_context


@pytest.fixture(scope="module")
def ca() -> trustme.CA:
    return trustme.CA()


@pytest.fixture(scope="module")
def client_cert(ca: trustme.CA) -> trustme.LeafCert:
    return ca.issue_cert("airflow")


def test_defaults_verify_against_system_cas() -> None:
    context = build_ssl_context({"ssl": True})

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert context.server_hostname is None


def test_ca_file_and_pem_are_trusted(ca: trustme.CA, tmp_path) -> None:
    ca_path = tmp_path / "ca.pem"
    ca.cert_pem.write_to_path(str(ca_path))

    from_file = build_ssl_context({"ssl_ca_certs": str(ca_path)})
    from_pem = build_ssl_context({"ssl_ca_cert_pem": ca.cert_pem.bytes().decode()})

    assert from_file.get_ca_certs() == from_pem.get_ca_certs()
    assert len(from_pem.get_ca_certs()) == 1


def test_ssl_verify_false_disables_verification_and_warns(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        context = build_ssl_context({"ssl_verify": False})

    assert context.verify_mode == ssl.CERT_NONE
    assert not context.check_hostname
    assert "not verified" in caplog.text


@pytest.mark.parametrize("value", ["false", "yes", 0, None])
def test_ssl_verify_must_be_a_boolean(value) -> None:
    with pytest.raises(ValueError, match="ssl_verify extra must be true or false"):
        build_ssl_context({"ssl_verify": value})


def test_client_cert_from_files(client_cert: trustme.LeafCert, tmp_path) -> None:
    cert_path, key_path = tmp_path / "client.pem", tmp_path / "client.key"
    client_cert.cert_chain_pems[0].write_to_path(str(cert_path))
    client_cert.private_key_pem.write_to_path(str(key_path))

    with mock.patch.object(BrokerSSLContext, "load_cert_chain") as load:
        build_ssl_context(
            {"ssl_certfile": str(cert_path), "ssl_keyfile": str(key_path)}
        )

    load.assert_called_once_with(str(cert_path), str(key_path))


def test_client_cert_from_pem(client_cert: trustme.LeafCert) -> None:
    # load_cert_chain fails on a cert that doesn't match the key, so this loads both
    build_ssl_context(
        {
            "ssl_cert_pem": client_cert.cert_chain_pems[0].bytes().decode(),
            "ssl_key_pem": client_cert.private_key_pem.bytes().decode(),
        }
    )


def test_client_key_without_cert_is_rejected() -> None:
    with pytest.raises(ValueError, match="client key"):
        build_ssl_context({"ssl_keyfile": "/certs/client.key"})


def test_server_hostname_overrides_the_connected_host() -> None:
    context = build_ssl_context({"ssl_server_hostname": "rabbit.internal"})

    with mock.patch.object(ssl.SSLContext, "wrap_bio") as wrap_bio:
        context.wrap_bio(None, None, server_hostname="10.0.0.5")
    with mock.patch.object(ssl.SSLContext, "wrap_socket") as wrap_socket:
        context.wrap_socket(None, server_hostname="10.0.0.5")

    wrap_bio.assert_called_once_with(None, None, server_hostname="rabbit.internal")
    wrap_socket.assert_called_once_with(None, server_hostname="rabbit.internal")
