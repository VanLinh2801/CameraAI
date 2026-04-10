FROM nvcr.io/nvidia/deepstream:7.0-gc-triton-devel

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       python3-gi \
       python3-gst-1.0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cameraai/deepstream

COPY deepstream/app.py /opt/cameraai/deepstream/app.py
COPY deepstream/start.sh /opt/cameraai/deepstream/start.sh
COPY deepstream/config /opt/cameraai/deepstream/config

RUN chmod +x /opt/cameraai/deepstream/start.sh

ENTRYPOINT ["/opt/cameraai/deepstream/start.sh"]
