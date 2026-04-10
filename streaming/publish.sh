#!/usr/bin/env bash
set -euo pipefail

input_video="${INPUT_VIDEO:-/workspace/12h.26.9.22.mp4}"
rtsp_url="${RTSP_URL:-rtsp://127.0.0.1:8554/camera}"
input_fps="${INPUT_FPS:-30}"

if [[ ! -f "${input_video}" ]]; then
  echo "Input video not found: ${input_video}" >&2
  exit 1
fi

while true; do
  echo "Starting RTSP publish: ${input_video} -> ${rtsp_url}" >&2

  ffmpeg -hide_banner -loglevel info \
    -stream_loop -1 -re -i "${input_video}" \
    -an \
    -vf "fps=${input_fps},format=yuv420p" \
    -c:v libx264 \
    -preset veryfast \
    -tune zerolatency \
    -profile:v main \
    -pix_fmt yuv420p \
    -x264-params "keyint=${input_fps}:min-keyint=${input_fps}:scenecut=0" \
    -f rtsp \
    -rtsp_transport tcp \
    "${rtsp_url}"

  echo "ffmpeg exited; retrying in 2 seconds" >&2
  sleep 2
done
