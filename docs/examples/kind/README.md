# Provider test environment on kind

A kind cluster with Airflow, RabbitMQ and Postgres, the provider installed from your checkout, and one DAG per
feature. Everything lives in the `rabbitmq-provider` cluster and namespace, and `./kind.sh down` removes all of it.

| Component  | What it is                                                                          | From the host                                  |
|------------|-------------------------------------------------------------------------------------|------------------------------------------------|
| `airflow`  | Airflow 3.3.2 standalone (API server, scheduler, DAG processor, triggerer)          | http://localhost:8080 (no login)               |
| `rabbitmq` | RabbitMQ 4: plain AMQP on 5672, mutual TLS on 5671 (client certificate required)    | http://localhost:15672 (`airflow` / `airflow`) |
| `postgres` | Airflow's metadata database                                                         |                                                |

Needs `kind`, `kubectl`, `openssl` and podman (or docker). With podman, `kind.sh` sets
`KIND_EXPERIMENTAL_PROVIDER=podman` itself and runs the node on its own network, `kind-rabbitmq-provider`, with
podman's DNS server off. That DNS server can't start when something in the podman machine already listens on port
53, and the single node doesn't need it.

RabbitMQ is pinned to 4.3.6: 4.4.0 hangs at boot importing the user from `definitions.json`.

## Lifecycle

```bash
./kind.sh up        # create or update everything; safe to re-run
./kind.sh status    # pods and URLs
./kind.sh logs      # follow Airflow (scheduler, triggerer and API server in one stream)
./kind.sh restart   # restart Airflow after editing src/ or plugins/
./kind.sh verify    # trigger every DAG and check each ends as the walkthrough says
./kind.sh publish asset_events_queue '{"hello": "asset"}'   # publish a message
./kind.sh down      # delete the cluster, its network, the built image and k8s/generated/
```

`up` generates a CA, a server certificate, a client certificate and Airflow's Fernet key into `k8s/generated/`
(gitignored). Then it builds the image from `../local-airflow/Containerfile`, creates the cluster, loads the image
into it and applies `k8s/` with kustomize. Re-running it rebuilds the image and restarts Airflow; the database, the
certificates and the key stay. The fixed Fernet key is what keeps the stored connections readable across restarts.

`verify` is the quick regression check after a provider change: it prints `ok` or `FAIL` per DAG, with the tasks
that didn't end as expected, and exits non-zero on any failure. It takes about two minutes.

`down` deletes the `rabbitmq-provider` kind cluster (pods, volumes, images pulled inside it, the kubeconfig
context), its podman network, the `localhost/rabbitmq-provider-airflow:kind` image and `k8s/generated/`. It leaves base images pulled to
your machine, such as `apache/airflow` and `kindest/node`, which other setups share. Every `kubectl` call in the
script names the `kind-rabbitmq-provider` context, so it never touches another cluster.

Other versions: `AIRFLOW_VERSION=3.1.7 PYTHON_VERSION=3.11 ./kind.sh up`. The walkthrough assumes Airflow 3
(`rmq_07` needs asset watchers).

## Editing the provider

The checkout is mounted into the kind node. `src/` is mounted into the Airflow pod and installed in editable mode,
`dags/` is the DAGs folder and `plugins/` the plugins folder.

- DAG files: picked up within about 10 seconds.
- `src/` or `plugins/rmq_helpers.py`: `./kind.sh restart`.

`plugins/rmq_helpers.py` holds code the DAGs share, including the trigger's `apply_function`. It's in the plugins
folder because the triggerer imports `apply_function` and only has the plugins folder on `sys.path`, not the DAGs
folder. Your own `apply_function`s need the same.
- `pyproject.toml`, `k8s/`: `./kind.sh up`.

## What's set up

**Connections** (Admin > Connections), from `k8s/airflow/connections.py`. They're created only if missing, so UI edits
survive restarts.

| Connection                    | What it shows                                                                       |
|-------------------------------|-------------------------------------------------------------------------------------|
| `rabbitmq_default`            | Plain AMQP, host `rabbitmq`, port 5672                                              |
| `rabbitmq_tls`                | `ssl: true` with CA, client cert and key as file paths; no port, so 5671            |
| `rabbitmq_tls_pem`            | The same certificates as PEM contents in the extras                                 |
| `rabbitmq_tls_alias`          | Host `rabbitmq-alias`, not in the server certificate; `ssl_server_hostname` fixes it |
| `rabbitmq_tls_noverify`       | `ssl_verify: false`: connects to `rabbitmq-alias` anyway, with a warning            |
| `rabbitmq_tls_no_client_cert` | Broken on purpose: the broker rejects it                                            |
| `rabbitmq_tls_string_flag`    | Broken on purpose: `"ssl": "yes"` is rejected                                       |

**Broker topology**, from `k8s/rabbitmq/definitions.json`: one set of queues per DAG, plus

- `demo_exchange` (direct) routing `demo` to `demo_exchange_queue`
- `events` (topic) routing `order.*` to `trigger_queue`
- `unbound_exchange` (direct, no bindings), for unroutable messages
- `full_queue` (`x-max-length: 0`, `reject-publish`), which nacks every publish

## Walkthrough

DAGs start paused. For each one: unpause it, trigger it (▶), and open the run's Grid view. Each DAG checks its own
results in `check_*` tasks, so a green run means the feature works. The task logs print what was published and
consumed, and http://localhost:15672 > Queues shows message counts while things run.

### 1. Publish and sense: `rmq_01_publish_and_sense`

Publishes with pika (sync) and aio-pika (async), through the default exchange and through `demo_exchange`. A
`RabbitMQSensor` consumes each message.

Expect: 8 green tasks. In a `wait_*` task's XCom tab you'll see the payload: `body`, `routing_key`, `exchange`,
`redelivered`, and so on.

### 2. Properties, JSON and binary bodies: `rmq_02_properties_and_json`

- `publish_json_with_properties` sets templated AMQP properties: `message_id` is the run id, `headers.try` the try
  number, plus `delivery_mode`, `priority`, `expiration` and `app_id`. Check the rendered values in the task's
  *Rendered Template* tab.
- `wait_json` uses `deserialize="json"`, so `body` in XCom is a dict, and `check_json` asserts on it.
- `publish_binary` sends non-UTF-8 bytes asynchronously, and the sensor returns them base64-encoded with
  `body_encoding: base64`.

To see the properties on the broker instead, pause after `publish_json_with_properties` (mark `wait_json` as skipped
before it runs) and use *Get messages* on `props_queue` in the management UI.

### 3. Batches: `rmq_03_batch`

One operator publishes a list over a single connection and channel: a str, bytes, an item with its own
`routing_key`, and an item whose `properties` merge over the operator's. It runs sync and async.

Expect: each publisher's XCom `return_value` is `4`. `check_batches` drains both queues and checks there are 6
messages on `batch_queue`, 2 on `batch_other_queue`, the right `app_id`s and 2 JSON items.

Set the scheduler log level to DEBUG to see one `Publishing message i/n` line per item; at INFO there's one line per
batch.

### 4. Delivery checks: `rmq_04_delivery_checks`

All green. It covers both sides of `confirm` and `mandatory`:

- `*_rejected_without_confirm_succeeds`: with `confirm=False`, a publish into `full_queue` succeeds although the
  broker drops the message. This is why `confirm` defaults to true.
- `*_unroutable_without_mandatory_succeeds`: without `mandatory`, an unroutable message is dropped silently.
- `*_routable_with_mandatory_succeeds`: `mandatory=True` is fine when the message has somewhere to go.
- `check_nack_raises` and `check_unroutable_raises` call the hook sync and async, and assert that the failing cases
  raise `MessageNotDeliveredError` with `reason` `nacked` / `unroutable`. Their logs print the exceptions.

### 5. Sensor modes: `rmq_05_sensor_modes`

- `peek_without_ack` (`auto_ack=False`) returns the message and puts it back. `consume_with_ack` then gets the same
  message with `redelivered: true` and removes it. `check_peek` asserts both and that the queue is empty.
- `wait_in_reschedule_mode` runs in `mode="reschedule"`. It shows as *up for reschedule* (worker slot freed) for
  about 30 seconds, until `publish_later` sends its message.

### 6. Deferrable trigger: `rmq_06_deferrable_trigger`

`wait_for_high_priority_order` defers on `RabbitMQTrigger`, which declares and binds `trigger_queue` to the topic
exchange `events` with `order.*`. Its `apply_function`, `rmq_helpers.only_priority` from `plugins/`, skips anything not
`"priority": "high"`.

- While it waits, the task is *deferred* (purple) and runs in the triggerer, not on a worker.
- `publish_events` sends a low-priority `order.created` (skipped by the function), a high-priority `invoice.paid`
  (doesn't match the binding, so it never reaches the queue) and a high-priority `order.cancelled` (accepted).
- Expect: the XCom of the deferred task is the function's return value: `id: 3`, `accepted_by: only_priority`.
  `check_event` also checks the queue is empty, which shows the skipped message was acked.

Run it twice: the second run works the same way, because the trigger never leaves skipped messages behind.

### 7. Asset watcher (event-driven DAGs): `rmq_07_asset_watcher.py`

1. Unpause `rmq_07_asset_consumer`. Its schedule is the asset `rabbitmq_asset_events`, watched by a
   `RabbitMQTrigger` on `asset_events_queue`. The triggerer starts the watcher once the DAG is unpaused.
2. Publish a message: trigger `rmq_07_asset_producer`, or from your terminal:

   ```bash
   ./kind.sh publish asset_events_queue '{"hello": "asset"}'
   ```

3. Within a few seconds `rmq_07_asset_consumer` gets a run. `show_triggering_message` logs the asset event, whose
   `extra` holds the message payload. *Assets* in the UI lists the event too.

Every message makes one run. Publish three in a row and you'll get three runs.

### 8. TLS: `rmq_08_tls`

One chain that publishes and consumes, sync and async, over each TLS connection: certificate files, PEM contents,
the `ssl_server_hostname` override and `ssl_verify: false`. It ends with a deferred trigger over TLS (aio-pika in the
triggerer).

Expect: all green. In a `rabbitmq_tls_noverify_*` log you'll see
`ssl_verify is false: the RabbitMQ broker certificate is not verified`. In the management UI, *Connections* shows
the TLS connections with `SSL / TLS: ●` while the DAG runs.

To check that the hostname override does the work, edit `rabbitmq_tls_alias` in the UI, remove
`ssl_server_hostname` from the extras and rerun a `rabbitmq_tls_alias_*` task. It fails with a certificate
hostname mismatch. Put it back afterwards.

### 9. Failures: `rmq_99_expected_failures`

`retries=0`. Every `fail_*` task should end **red** (the two `publish_*` helpers stay green). Open each log for the
error:

| Task                              | Error                                                                         |
|-----------------------------------|-------------------------------------------------------------------------------|
| `fail_*_nacked_by_full_queue`     | `MessageNotDeliveredError: Message nacked by the broker ...`                  |
| `fail_*_unroutable_with_mandatory`| `MessageNotDeliveredError: Message unroutable by the broker ...`              |
| `fail_*_missing_exchange`         | `NOT_FOUND - no exchange 'no_such_exchange'`                                  |
| `fail_invalid_property`           | `ValueError` on `priority`, raised before connecting                          |
| `fail_sensor_max_xcom_bytes`      | The body is over `max_xcom_bytes`. The message stays on `big_queue`           |
| `fail_sensor_deserialize_json`    | The body isn't valid JSON. The message stays on `not_json_queue`              |
| `fail_tls_without_client_cert`    | `ConnectionError`: the broker requires a client certificate                   |
| `fail_tls_string_flag`            | `ConnectionError ... The ssl extra must be true or false, got 'yes'`          |

`big_queue` and `not_json_queue` gain a message every run, since failing sensors leave it in place. Purge them in the
management UI if you like.

## From the host

The broker is also exposed on localhost, so you can test against it outside Airflow, for example with the hook:

```python
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook

RabbitMQHook(connection_uri="amqp://airflow:airflow@localhost:5672").publish_sync(
    "from the host", exchange="", routing_key="demo_queue"
)
```

For TLS from the host, use port 5671 with `k8s/generated/ca.pem`, `client.pem` and `client.key`. The server
certificate lists `localhost` and `127.0.0.1`.

## Troubleshooting

- `./kind.sh status` shows pod state. `kubectl --context kind-rabbitmq-provider -n rabbitmq-provider describe pod -l app=airflow`
  shows why a pod isn't ready.
- A DAG missing from the UI: *Browse > DAG import errors*, or `./kind.sh logs | grep -i error`.
- A deferred task that fails with `No module named ...`: the triggerer can't import the `apply_function`. Put its
  module in `plugins/` (or install it in the image), not in `dags/`.
- A deferred task that never finishes: the triggerer logs (in `./kind.sh logs`) show `Cannot connect to RabbitMQ`
  when the connection is wrong; the trigger keeps retrying instead of failing.
