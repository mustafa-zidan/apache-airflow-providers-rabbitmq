"""Integration tests for TLS configured through connection extras."""

import json
import os
from typing import Any, Dict
from unittest import mock

import pytest
import trustme

try:
    import docker
    from docker.errors import DockerException
    from testcontainers.community.rabbitmq import RabbitMqContainer

    docker.from_env().ping()
    DOCKER_AVAILABLE = True
except (ImportError, DockerException, OSError):
    DOCKER_AVAILABLE = False

from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
from airflow.provider.rabbitmq.operators.rabbitmq_producer import (
    RabbitMQProducerOperator,
)
from airflow.provider.rabbitmq.sensors.rabbitmq_sensor import RabbitMQSensor

# The broker certificate names neither localhost nor 127.0.0.1, so connecting
# also checks that ssl_server_hostname is used for verification.
SERVER_HOSTNAME = "rabbit.internal"

TLS_CONFIG = b"""
listeners.ssl.default = 5671
ssl_options.cacertfile = /etc/rabbitmq/certs/ca.pem
ssl_options.certfile = /etc/rabbitmq/certs/server.pem
ssl_options.keyfile = /etc/rabbitmq/certs/server.key
ssl_options.verify = verify_peer
ssl_options.fail_if_no_peer_cert = true
"""


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker is not available")
class TestRabbitMQTLSIntegration:
    """Publish and consume over mutual TLS with the settings in the connection extras"""

    queue: str = "tls_queue"
    conn_id: str = "rabbitmq_tls"
    ca: trustme.CA = None
    client_cert: trustme.LeafCert = None
    host: str = None
    port: int = None

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def rabbitmq_container(cls, tmp_path_factory):
        """Start a RabbitMQ container that requires a client certificate"""
        cls.ca = trustme.CA()
        cls.client_cert = cls.ca.issue_cert("airflow")
        server_cert = cls.ca.issue_cert(SERVER_HOSTNAME)

        container = (
            RabbitMqContainer("rabbitmq:4")
            .with_exposed_ports(5671)
            .with_copy_into_container(TLS_CONFIG, "/etc/rabbitmq/conf.d/20-tls.conf")
            .with_copy_into_container(
                cls.ca.cert_pem.bytes(), "/etc/rabbitmq/certs/ca.pem"
            )
            .with_copy_into_container(
                server_cert.cert_chain_pems[0].bytes(), "/etc/rabbitmq/certs/server.pem"
            )
            .with_copy_into_container(
                server_cert.private_key_pem.bytes(), "/etc/rabbitmq/certs/server.key"
            )
        )
        with container:
            cls.host = container.get_container_host_ip()
            cls.port = container.get_exposed_port(5671)

            certs = tmp_path_factory.mktemp("certs")
            cls.ca.cert_pem.write_to_path(str(certs / "ca.pem"))
            cls.client_cert.cert_chain_pems[0].write_to_path(str(certs / "client.pem"))
            cls.client_cert.private_key_pem.write_to_path(str(certs / "client.key"))

            # Certificates as files on disk
            airflow_conn = cls._airflow_conn(
                {
                    "ssl_ca_certs": str(certs / "ca.pem"),
                    "ssl_certfile": str(certs / "client.pem"),
                    "ssl_keyfile": str(certs / "client.key"),
                }
            )
            with mock.patch.dict(
                os.environ, {f"AIRFLOW_CONN_{cls.conn_id.upper()}": airflow_conn}
            ):
                yield

    @classmethod
    def _airflow_conn(cls, tls_extras: Dict[str, Any]) -> str:
        return json.dumps(
            {
                "conn_type": "rabbitmq",
                "host": cls.host,
                "port": cls.port,
                "login": "guest",
                "password": "guest",
                "extra": {
                    "ssl": True,
                    "ssl_server_hostname": SERVER_HOSTNAME,
                    **tls_extras,
                },
            }
        )

    def _pem_extras(self) -> Dict[str, Any]:
        """The same certificates as PEM contents, as kept in a secrets backend"""
        return {
            "ssl_ca_cert_pem": self.ca.cert_pem.bytes().decode(),
            "ssl_cert_pem": self.client_cert.cert_chain_pems[0].bytes().decode(),
            "ssl_key_pem": self.client_cert.private_key_pem.bytes().decode(),
        }

    def _declare_queue(self) -> None:
        with RabbitMQHook(conn_id=self.conn_id).get_sync_connection_cm() as conn:
            conn.channel().queue_declare(queue=self.queue, durable=True)

    def _poke(self, conn_id: str) -> str:
        """Return the body of the message the sensor consumes"""
        sensor = RabbitMQSensor(
            task_id="tls_sensor",
            conn_id=conn_id,
            queue_name=self.queue,
            poke_interval=1,
            timeout=10,
            mode="poke",
        )
        result = sensor.poke({})
        assert result.is_done is True
        return result.xcom_value["body"]

    @pytest.mark.parametrize("use_async", [False, True])
    def test_publish_and_consume_with_cert_files(self, use_async: bool) -> None:
        self._declare_queue()
        RabbitMQProducerOperator(
            task_id="tls_producer",
            conn_id=self.conn_id,
            message="over tls",
            exchange="",
            routing_key=self.queue,
            use_async=use_async,
        ).execute({})

        assert self._poke(self.conn_id) == "over tls"

    @pytest.mark.parametrize("use_async", [False, True])
    def test_publish_and_consume_with_pem_contents(self, use_async: bool) -> None:
        self._declare_queue()
        pem_conn = self._airflow_conn(self._pem_extras())
        with mock.patch.dict(os.environ, {"AIRFLOW_CONN_RABBITMQ_TLS_PEM": pem_conn}):
            RabbitMQProducerOperator(
                task_id="tls_producer",
                conn_id="rabbitmq_tls_pem",
                message="pem over tls",
                exchange="",
                routing_key=self.queue,
                use_async=use_async,
            ).execute({})

            assert self._poke("rabbitmq_tls_pem") == "pem over tls"

    @pytest.mark.parametrize("use_async", [False, True])
    async def test_wrong_ca_fails(self, use_async: bool) -> None:
        wrong_ca = trustme.CA().cert_pem.bytes().decode()
        await self._assert_connect_fails(
            {**self._pem_extras(), "ssl_ca_cert_pem": wrong_ca}, use_async
        )

    @pytest.mark.parametrize("use_async", [False, True])
    async def test_missing_client_cert_fails(self, use_async: bool) -> None:
        ca_only = {"ssl_ca_cert_pem": self.ca.cert_pem.bytes().decode()}
        await self._assert_connect_fails(ca_only, use_async)

    async def _assert_connect_fails(
        self, tls_extras: Dict[str, Any], use_async: bool
    ) -> None:
        bad_conn = self._airflow_conn(tls_extras)
        with mock.patch.dict(os.environ, {"AIRFLOW_CONN_RABBITMQ_TLS_BAD": bad_conn}):
            hook = RabbitMQHook(conn_id="rabbitmq_tls_bad")
            with pytest.raises(ConnectionError, match="Failed to connect"):
                if use_async:
                    await hook.get_async_connection()
                else:
                    hook.get_sync_connection()
