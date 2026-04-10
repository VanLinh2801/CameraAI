#!/usr/bin/env bash
set -euo pipefail

retry_delay="${DEEPSTREAM_RTSP_RECONNECT_INTERVAL_SEC:-5}"

mkdir -p "$(dirname "${DEEPSTREAM_METADATA_PATH:-/data/metadata/events.jsonl}")"

while true; do
  echo "Starting DeepStream pipeline" >&2
  if python3 /opt/cameraai/deepstream/app.py; then
    exit 0
  fi
  exit_code=$?

  if [[ "${exit_code}" -eq 2 ]]; then
    echo "DeepStream configuration error; exiting without retry" >&2
    exit "${exit_code}"
  fi

  echo "DeepStream pipeline exited unexpectedly; retrying in ${retry_delay}s" >&2
  sleep "${retry_delay}"
done
