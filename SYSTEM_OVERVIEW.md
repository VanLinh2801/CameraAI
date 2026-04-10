# CameraAI System Overview

## 1. Project Goals

Build a real-time video analytics system with two primary goals:

- Human detection
- Automatic ID assignment per person (multi-object tracking)

The initial input is an existing video file in the workspace. This file is converted into a simulated RTSP camera stream so DeepStream can process it like a real camera source.

## 2. Agreed Scope

- Deploy on an Ubuntu server (accessed via SSH)
- Run DeepStream inside Docker
- Run the RTSP emulator on the same machine as DeepStream
- Use RTSP as the pipeline input protocol
- Baseline detection/tracking stack: PeopleNet + nvtracker
- Desired outputs:
  - Annotated video (bounding boxes + track IDs)
  - Metadata (timestamp, class, confidence, bbox, track_id)
  - Real-time stream/display

## 3. Baseline Versions (Pinned)

These versions are pinned to reduce deployment mismatch risk:

- Python 3.10.12
- Docker 28.1.1
- DeepStream 7.0.0
- CUDA Driver 13.0
- CUDA Runtime 12.2
- TensorRT 8.6
- cuDNN 8.9
- libNVWarp360 2.0.1d3

Rules:

- Do not upgrade the stack unless there is a clear compatibility reason
- Do not mix DeepStream 7.0 with DeepStream 9.x images or TensorRT 10.x packages in this project

## 4. High-Level Architecture

```text
[Local video file]
      |
      v
[FFmpeg loop publisher]
      |
      v
[MediaMTX RTSP server] ---> rtsp://127.0.0.1:8554/camera
                                   |
                                   v
                        [DeepStream pipeline]
                                   |
              +--------------------+--------------------+
              |                    |                    |
              v                    v                    v
      [Annotated video]   [Realtime output stream]   [Metadata events]
```

## 5. Current Modules

### Streaming (Implemented)

Module goals:

- Turn the sample video into an infinite RTSP camera-like stream
- Provide a stable RTSP URL for DeepStream ingestion

Current design:

- MediaMTX as RTSP server
- FFmpeg as publisher to read and push video into RTSP
- Docker Compose to start both services together
- Host network mode to simplify same-machine connectivity with DeepStream

Defaults:

- Input video: 12h.26.9.22.mp4
- RTSP output: rtsp://127.0.0.1:8554/camera

### DeepStream Processing (MVP Implemented)

Module goals:

- Ingest the RTSP stream from the streaming module
- Detect people with PeopleNet
- Track people across frames with nvtracker
- Publish an annotated RTSP output stream
- Export metadata as JSONL

Defaults:

- RTSP input: rtsp://127.0.0.1:8554/camera
- RTSP annotated output: rtsp://127.0.0.1:8554/analytics
- Metadata output: deepstream/output/events.jsonl

## 6. Files Already Created

- docker-compose.yml
- streaming/mediamtx.yml
- streaming/Dockerfile.publisher
- streaming/publish.sh
- deepstream/Dockerfile
- deepstream/start.sh
- deepstream/app.py
- deepstream/config/pgie_peoplenet_config.txt.template
- deepstream/config/nvtracker_config.txt
- deepstream/config/labels_peoplenet.txt
- README.md

## 7. Streaming Runtime Flow

1. Start RTSP server and publisher with Docker Compose
2. Publisher reads the video in infinite loop mode
3. Publisher pushes an H.264 stream to MediaMTX over RTSP/TCP
4. MediaMTX exposes the stream at path /camera
5. DeepStream (next module) consumes that RTSP URL

## 8. DeepStream Processing (MVP Scope)

Current MVP goals:

- Ingest RTSP stream from the streaming module
- Detect people (primary inference)
- Assign and maintain track IDs across frames
- Overlay bounding boxes and IDs on output
- Export metadata in a consistent schema

Planned components:

- source: RTSP input
- streammux + decode
- nvinfer (PeopleNet)
- nvtracker
- nvdsosd (overlay)
- sink:
  - rtsp/file/display by mode
  - metadata exporter

Current MVP output mode:

- RTSP annotated stream
- JSONL metadata exporter

## 9. End-to-End Acceptance Criteria

Streaming:

- RTSP URL can be opened by ffplay/VLC
- Stream does not stop when the source video ends (infinite loop)
- Services recover after container restart

DeepStream:

- RTSP ingest is successful
- Person class detection is correct
- IDs stay stable while objects move
- Metadata includes all required fields

## 10. Module Responsibility Boundaries

Streaming module:

- Only provides a stable RTSP camera source
- Contains no AI logic

DeepStream module:

- Handles AI inference, tracking, and analytics outputs
- Should not depend on specific source file content, only on a valid RTSP source

## 11. Expansion After MVP Stability

- Multiple RTSP camera paths
- Metadata push to HTTP/Kafka
- Dashboard for tracker events
- Rule-based alerts (zone, dwell time, crowd threshold)
- CI/CD and preflight validation before deployment

## 12. Key Decisions Summary

- Keep RTSP on the same machine as DeepStream for stability and easier debugging
- Keep the agreed baseline versions pinned
- Prioritize the critical flow first: stable stream -> person detection -> ID tracking -> outputs
- Build and integrate by module to reduce integration risk
