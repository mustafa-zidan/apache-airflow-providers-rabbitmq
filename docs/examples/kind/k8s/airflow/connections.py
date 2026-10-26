"""Write the RabbitMQ connections as a file for `airflow connections import`."""

import json
import sys

CERTS = "/opt/airflow/certs"


def read(name: str) -> str:
    with open(f"{CERTS}/{name}", encoding="utf-8") as f:
        return f.read()


def rabbitmq(host: str = "rabbitmq", port=None, **extra) -> dict:
    conn = {"conn_type": "rabbitmq", "host": host, "login": "airflow", "password": "airflow"}
    if port:
        conn["port"] = port
    if extra:
        conn["extra"] = json.dumps(extra)
    return conn


cert_files = {
    "ssl_ca_certs": f"{CERTS}/ca.pem",
    "ssl_certfile": f"{CERTS}/client.pem",
    "ssl_keyfile": f"{CERTS}/client.key",
}

connections = {
    # Plain AMQP on 5672
    "rabbitmq_default": rabbitmq(port=5672),
    # Mutual TLS, certificates as files; no port, so 5671 is the default
    "rabbitmq_tls": rabbitmq(ssl=True, **cert_files),
    # Mutual TLS, certificates as PEM contents (as a secrets backend would hold them)
    "rabbitmq_tls_pem": rabbitmq(
        ssl=True,
        ssl_ca_cert_pem=read("ca.pem"),
        ssl_cert_pem=read("client.pem"),
        ssl_key_pem=read("client.key"),
    ),
    # Host isn't in the server certificate; ssl_server_hostname makes it verify
    "rabbitmq_tls_alias": rabbitmq(
        host="rabbitmq-alias", ssl=True, ssl_server_hostname="rabbitmq", **cert_files
    ),
    # Skips verifying the broker certificate; logs a warning on every connection
    "rabbitmq_tls_noverify": rabbitmq(
        host="rabbitmq-alias",
        ssl=True,
        ssl_verify=False,
        ssl_certfile=f"{CERTS}/client.pem",
        ssl_keyfile=f"{CERTS}/client.key",
    ),
    # Broken on purpose, used by rmq_99_expected_failures
    "rabbitmq_tls_no_client_cert": rabbitmq(ssl=True, ssl_ca_certs=f"{CERTS}/ca.pem"),
    "rabbitmq_tls_string_flag": rabbitmq(ssl="yes", **cert_files),
}

json.dump(connections, open(sys.argv[1], "w", encoding="utf-8"), indent=2)
