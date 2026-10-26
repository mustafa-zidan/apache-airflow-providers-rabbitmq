#!/usr/bin/env bash
# Airflow + RabbitMQ (plain and mutual TLS) + Postgres on a kind cluster, with the
# provider installed from this checkout.
#   ./kind.sh up                    create or update everything (safe to re-run)
#   ./kind.sh restart               restart Airflow, e.g. after editing src/
#   ./kind.sh status                pods and URLs
#   ./kind.sh logs                  follow the Airflow logs
#   ./kind.sh publish KEY MSG [EX]  publish MSG with routing key KEY (default exchange)
#   ./kind.sh verify                trigger every DAG and check the results
#   ./kind.sh down                  delete the cluster, the built image and k8s/generated
set -euo pipefail

cluster=rabbitmq-provider
namespace=rabbitmq-provider
image=localhost/rabbitmq-provider-airflow:kind

kind_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$kind_dir/../../.." && pwd)"
# Certificates and the Fernet key, created by `up` and never committed.
generated_dir="$kind_dir/k8s/generated"

if command -v podman >/dev/null; then
  engine=podman
  export KIND_EXPERIMENTAL_PROVIDER=podman
  # A network of its own, with podman's DNS server (aardvark-dns) off: it fails to
  # start when anything in the podman machine already listens on port 53, and the
  # single node doesn't need it.
  export KIND_EXPERIMENTAL_PODMAN_NETWORK="kind-$cluster"
else
  engine=docker
fi

# Never act on whatever cluster the current kubectl context points at.
kc() { kubectl --context "kind-$cluster" -n "$namespace" "$@"; }

cluster_exists() { kind get clusters 2>/dev/null | grep -qx "$cluster"; }

gen_fernet_key() {
  [[ -f "$generated_dir/fernet_key" ]] && return
  mkdir -p "$generated_dir"
  # Airflow encrypts connections with it. Standalone would generate one per pod,
  # making the stored connections unreadable after every restart.
  openssl rand -base64 32 | tr '+/' '-_' >"$generated_dir/fernet_key"
}

gen_certs() {
  [[ -f "$generated_dir/client.key" ]] && return
  echo "Generating a CA, a server certificate and a client certificate in $generated_dir"
  mkdir -p "$generated_dir"
  cd "$generated_dir"
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 -sha256 \
    -subj "/CN=rabbitmq-provider-ca" -keyout ca.key -out ca.pem \
    -config <(printf '[req]\ndistinguished_name=dn\nx509_extensions=v3_ca\n[dn]\n[v3_ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n') \
    2>/dev/null
  # The server certificate lists "rabbitmq" but not "rabbitmq-alias".
  sign_leaf server rabbitmq serverAuth \
    "subjectAltName=DNS:rabbitmq,DNS:rabbitmq.$namespace.svc,DNS:rabbitmq.$namespace.svc.cluster.local,DNS:localhost,IP:127.0.0.1"
  sign_leaf client airflow clientAuth ""
  rm -f ./*.csr ./*.ext ./*.srl
  cd - >/dev/null
}

sign_leaf() {
  local name=$1 cn=$2 usage=$3 san=$4
  openssl req -newkey rsa:2048 -nodes -subj "/CN=$cn" \
    -keyout "$name.key" -out "$name.csr" 2>/dev/null
  printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=%s\nauthorityKeyIdentifier=keyid\n%s\n' \
    "$usage" "$san" >"$name.ext"
  openssl x509 -req -in "$name.csr" -CA ca.pem -CAkey ca.key -CAcreateserial \
    -days 365 -sha256 -extfile "$name.ext" -out "$name.pem" 2>/dev/null
}

build_image() {
  "$engine" build \
    --build-arg "AIRFLOW_VERSION=${AIRFLOW_VERSION:-3.3.2}" \
    --build-arg "PYTHON_VERSION=${PYTHON_VERSION:-3.12}" \
    -t "$image" -f "$kind_dir/../local-airflow/Containerfile" "$repo_dir"
}

load_image() {
  local archive
  archive="$(mktemp -d)/airflow.tar"
  if [[ $engine == podman ]]; then
    podman save --format docker-archive -o "$archive" "$image"
  else
    docker save -o "$archive" "$image"
  fi
  kind load image-archive "$archive" --name "$cluster"
  rm -rf "$(dirname "$archive")"
}

wait_ready() {
  for deployment in postgres rabbitmq airflow; do
    kc rollout status "deployment/$deployment" --timeout=10m
  done
}

print_urls() {
  cat <<EOF

Airflow UI           http://localhost:8080        (no login)
RabbitMQ management  http://localhost:15672       (airflow / airflow)
AMQP from the host   amqp://airflow:airflow@localhost:5672
AMQPS from the host  localhost:5671, client cert in $generated_dir
EOF
}

case "${1:-}" in
  up)
    gen_certs
    gen_fernet_key
    build_image
    if [[ $engine == podman ]] && ! podman network exists "$KIND_EXPERIMENTAL_PODMAN_NETWORK"; then
      podman network create --disable-dns "$KIND_EXPERIMENTAL_PODMAN_NETWORK" >/dev/null
    fi
    if ! cluster_exists; then
      sed "s|__REPO_DIR__|$repo_dir|g" "$kind_dir/kind-config.yaml" |
        kind create cluster --config -
    fi
    load_image
    existed=$(kc get deployment airflow -o name 2>/dev/null || true)
    kc apply -k "$kind_dir/k8s"
    # The image tag doesn't change on a rebuild, so pick the new one up explicitly.
    [[ -n $existed ]] && kc rollout restart deployment/airflow
    wait_ready
    print_urls
    ;;
  restart)
    kc rollout restart deployment/airflow
    kc rollout status deployment/airflow --timeout=10m
    ;;
  status)
    kc get pods -o wide
    print_urls
    ;;
  logs)
    kc logs -f deployment/airflow
    ;;
  publish)
    [[ $# -ge 3 ]] || { echo "usage: $0 publish ROUTING_KEY MESSAGE [EXCHANGE]" >&2; exit 2; }
    kc exec deployment/airflow -- python -c '
import sys
from airflow.provider.rabbitmq.hooks.rabbitmq_hook import RabbitMQHook
hook = RabbitMQHook(connection_uri="amqp://airflow:airflow@rabbitmq:5672")
hook.publish_sync(sys.argv[2], exchange=sys.argv[3], routing_key=sys.argv[1])
print("published")
' "$2" "$3" "${4:-}"
    ;;
  verify)
    kc exec deployment/airflow -- python /opt/airflow/scripts/verify.py
    ;;
  down)
    if cluster_exists; then
      kind delete cluster --name "$cluster"
    fi
    if [[ $engine == podman ]]; then
      podman network rm "$KIND_EXPERIMENTAL_PODMAN_NETWORK" >/dev/null 2>&1 || true
    fi
    "$engine" rmi -f "$image" 2>/dev/null || true
    rm -rf "$generated_dir"
    echo "Removed the $cluster cluster and its network, the $image image and $generated_dir."
    ;;
  *)
    sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
    ;;
esac
