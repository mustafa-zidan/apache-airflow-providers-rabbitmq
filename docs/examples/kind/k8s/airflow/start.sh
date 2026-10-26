#!/usr/bin/env bash
set -euo pipefail

until airflow db check >/dev/null 2>&1; do
  echo "Waiting for the metadata database..."
  sleep 2
done

airflow db migrate

# Existing connections are skipped, so edits made in the UI survive pod restarts.
python /opt/airflow/scripts/connections.py /tmp/connections.json
airflow connections import /tmp/connections.json

exec airflow standalone
