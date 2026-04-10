# CameraAI MVP

This repository now contains the MVP foundation for the project:

- A local RTSP server using MediaMTX
- A video publisher that loops the sample video and pushes it to RTSP
- A DeepStream pipeline that ingests the RTSP stream, runs PeopleNet + nvtracker,
  publishes an annotated RTSP stream, and writes metadata to JSONL

## Files

- `docker-compose.yml` runs the RTSP server and the publisher
- `streaming/mediamtx.yml` configures the RTSP server
- `streaming/Dockerfile.publisher` builds the FFmpeg publisher image
- `streaming/publish.sh` loops the local video and publishes it to RTSP
- `deepstream/Dockerfile` builds the DeepStream runtime image
- `deepstream/app.py` runs the DeepStream RTSP -> detect -> track -> RTSP pipeline
- `deepstream/config/*` contains the tracker config and the PeopleNet config template

## Default streams

- Input video: `12h.26.9.22.mp4`
- Source RTSP URL: `rtsp://127.0.0.1:8554/camera`
- Annotated RTSP URL: `rtsp://127.0.0.1:8554/analytics`
- Metadata JSONL: `deepstream/output/events.jsonl`

## Model prerequisites

The DeepStream service expects PeopleNet artifacts under `deepstream/models/peoplenet/`.

Supported options:

- Preferred: `model.engine`
- Or TAO export files:
  - `model.etlt` and `int8-calib.bin` for INT8
  - `model.etlt` and `labels.txt` for FP32 fallback when no calibration cache is available
- The runtime labels path is expected at `deepstream/models/peoplenet/labels.txt`

The container will fail fast with a clear startup error if no compatible PeopleNet model
artifacts are mounted.

## Run

1. Start the stack:

```bash
docker compose up -d --build
```

2. Check the source RTSP stream from the host:

```bash
ffplay rtsp://127.0.0.1:8554/camera
```

3. Check the annotated RTSP output:

```bash
ffplay rtsp://127.0.0.1:8554/analytics
```

4. Tail metadata events:

```bash
tail -f deepstream/output/events.jsonl
```

## Notes

- This setup is intended for Ubuntu Linux running Docker on the same server as DeepStream.
- The publisher loops the video forever so DeepStream can treat it like a live camera.
- The publisher re-encodes to H.264 for compatibility and stable RTSP ingest.
- The DeepStream container expects NVIDIA GPU access and a DeepStream 7.0-compatible host.
- Metadata is emitted as JSON Lines, one object per detection, for easy grep and replay.
