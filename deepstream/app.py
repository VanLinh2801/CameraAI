#!/usr/bin/env python3
import json
import os
import signal
import sys
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GObject", "2.0")

from gi.repository import GLib, Gst  # noqa: E402

import pyds  # noqa: E402


PGIE_CONFIG_TEMPLATE = Path("/opt/cameraai/deepstream/config/pgie_peoplenet_config.txt.template")
PGIE_CONFIG_RENDERED = Path("/tmp/pgie_peoplenet_config.txt")


@dataclass
class Settings:
    input_rtsp: str
    output_rtsp: str
    metadata_path: Path
    model_root: Path
    labels_path: Path
    tracker_config: Path
    output_width: int
    output_height: int
    output_fps: int
    source_id: str


class MetadataWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")

    def write(self, event: dict) -> None:
        try:
            self._handle.write(json.dumps(event, ensure_ascii=True) + "\n")
            self._handle.flush()
        except Exception as exc:  # pragma: no cover - best effort logging
            print(f"Failed to write metadata event: {exc}", file=sys.stderr)

    def close(self) -> None:
        self._handle.close()


def load_settings() -> Settings:
    return Settings(
        input_rtsp=os.environ.get("DEEPSTREAM_INPUT_RTSP", "rtsp://127.0.0.1:8554/camera"),
        output_rtsp=os.environ.get("DEEPSTREAM_OUTPUT_RTSP", "rtsp://127.0.0.1:8554/analytics"),
        metadata_path=Path(os.environ.get("DEEPSTREAM_METADATA_PATH", "/data/metadata/events.jsonl")),
        model_root=Path(os.environ.get("DEEPSTREAM_MODEL_ROOT", "/models/peoplenet")),
        labels_path=Path(
            os.environ.get(
                "DEEPSTREAM_LABELS_PATH",
                "/opt/cameraai/deepstream/config/labels_peoplenet.txt",
            )
        ),
        tracker_config=Path(
            os.environ.get(
                "DEEPSTREAM_TRACKER_CONFIG",
                "/opt/cameraai/deepstream/config/nvtracker_config.txt",
            )
        ),
        output_width=int(os.environ.get("DEEPSTREAM_OUTPUT_WIDTH", "1280")),
        output_height=int(os.environ.get("DEEPSTREAM_OUTPUT_HEIGHT", "720")),
        output_fps=int(os.environ.get("DEEPSTREAM_OUTPUT_FPS", "30")),
        source_id=os.environ.get("DEEPSTREAM_SOURCE_ID", "camera-01"),
    )


def ensure_required_paths(settings: Settings) -> dict:
    if not settings.model_root.exists():
        raise FileNotFoundError(
            f"PeopleNet model root does not exist: {settings.model_root}. "
            "Mount model files into deepstream/models/peoplenet."
        )

    engine_path = settings.model_root / "model.engine"
    etlt_path = settings.model_root / "model.etlt"
    calib_path = settings.model_root / "int8-calib.bin"
    if engine_path.exists():
        mode = "engine"
        network_mode = "1"
    elif etlt_path.exists() and calib_path.exists():
        mode = "etlt_int8"
        network_mode = "1"
    elif etlt_path.exists():
        mode = "etlt_fp32"
        network_mode = "0"
    else:
        raise FileNotFoundError(
            "No supported PeopleNet artifacts found. Expected one of: "
            "'model.engine', 'model.etlt', or both 'model.etlt' and 'int8-calib.bin'."
        )

    if not settings.labels_path.exists():
        raise FileNotFoundError(f"Labels file not found: {settings.labels_path}")

    if not settings.tracker_config.exists():
        raise FileNotFoundError(f"Tracker config file not found: {settings.tracker_config}")

    return {
        "mode": mode,
        "network_mode": network_mode,
        "engine_path": str(engine_path),
        "etlt_path": str(etlt_path),
        "calib_path": str(calib_path),
        "labels_path": str(settings.labels_path),
    }


def render_pgie_config(settings: Settings) -> Path:
    model_info = ensure_required_paths(settings)
    rendered = PGIE_CONFIG_TEMPLATE.read_text(encoding="utf-8")

    replacements = {
        "__MODEL_ROOT__": str(settings.model_root),
        "__LABELS_PATH__": model_info["labels_path"],
        "__NETWORK_MODE__": model_info["network_mode"],
        "__ENGINE_FILE_BLOCK__": "",
        "__MODEL_FILE_BLOCK__": "",
        "__OUTPUT_BLOB_NAMES_BLOCK__": "output-blob-names=output_bbox/BiasAdd;output_cov/Sigmoid",
    }

    if model_info["mode"] == "engine":
        replacements["__ENGINE_FILE_BLOCK__"] = f"model-engine-file={model_info['engine_path']}"
    else:
        model_file_block_lines = [
            f"tlt-encoded-model={model_info['etlt_path']}",
            "tlt-model-key=tlt_encode",
        ]
        if model_info["mode"] == "etlt_int8":
            model_file_block_lines.append(f"int8-calib-file={model_info['calib_path']}")
        replacements["__MODEL_FILE_BLOCK__"] = "\n".join(model_file_block_lines)

    for key, value in replacements.items():
        rendered = rendered.replace(key, value)

    PGIE_CONFIG_RENDERED.write_text(rendered, encoding="utf-8")
    return PGIE_CONFIG_RENDERED


def make_element(factory: str, name: str):
    element = Gst.ElementFactory.make(factory, name)
    if not element:
        raise RuntimeError(f"Failed to create element '{name}' from factory '{factory}'")
    return element


def cb_newpad(decodebin, decoder_src_pad, data):
    caps = decoder_src_pad.get_current_caps()
    if not caps:
        caps = decoder_src_pad.query_caps(None)
    if not caps:
        return

    gststruct = caps.get_structure(0)
    name = gststruct.get_name()
    features = caps.get_features(0)

    if "video" not in name:
        return

    if features and features.contains("memory:NVMM"):
        bin_ghost_pad = data.get_static_pad("src")
        if not bin_ghost_pad.set_target(decoder_src_pad):
            raise RuntimeError("Failed to link decodebin source pad to source bin ghost pad")
    else:
        raise RuntimeError("Decodebin did not pick an NVIDIA decoder plugin")


def decodebin_child_added(child_proxy, obj, name, user_data):
    if name.startswith("decodebin"):
        obj.connect("child-added", decodebin_child_added, user_data)

    if name.startswith("source"):
        if obj.find_property("latency") is not None:
            obj.set_property("latency", 200)
        if obj.find_property("drop-on-latency") is not None:
            obj.set_property("drop-on-latency", True)


def create_source_bin(index: int, uri: str):
    bin_name = f"source-bin-{index:02d}"
    nbin = Gst.Bin.new(bin_name)
    if not nbin:
        raise RuntimeError("Unable to create source bin")

    uri_decode_bin = make_element("uridecodebin", f"uri-decode-bin-{index}")
    uri_decode_bin.set_property("uri", uri)
    uri_decode_bin.connect("pad-added", cb_newpad, nbin)
    uri_decode_bin.connect("child-added", decodebin_child_added, nbin)
    nbin.add(uri_decode_bin)

    ghost_pad = Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC)
    if not ghost_pad:
        raise RuntimeError("Failed to create ghost pad for source bin")
    nbin.add_pad(ghost_pad)
    return nbin


def osd_sink_pad_buffer_probe(pad, info, user_data):
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        return Gst.PadProbeReturn.OK

    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    if not batch_meta:
        return Gst.PadProbeReturn.OK

    l_frame = batch_meta.frame_meta_list
    while l_frame:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break

        frame_timestamp = datetime.now(timezone.utc).isoformat()
        l_obj = frame_meta.obj_meta_list
        while l_obj:
            try:
                obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
            except StopIteration:
                break

            class_label = obj_meta.obj_label or "unknown"
            if class_label == "person":
                rect = obj_meta.rect_params
                obj_meta.text_params.display_text = f"{class_label} #{int(obj_meta.object_id)}"
                user_data.write(
                    {
                        "timestamp": frame_timestamp,
                        "source_id": os.environ.get("DEEPSTREAM_SOURCE_ID", "camera-01"),
                        "frame_num": int(frame_meta.frame_num),
                        "class": class_label,
                        "confidence": round(float(obj_meta.confidence), 6),
                        "bbox": {
                            "left": round(float(rect.left), 2),
                            "top": round(float(rect.top), 2),
                            "width": round(float(rect.width), 2),
                            "height": round(float(rect.height), 2),
                        },
                        "track_id": int(obj_meta.object_id),
                    }
                )

            try:
                l_obj = l_obj.next
            except StopIteration:
                break

        try:
            l_frame = l_frame.next
        except StopIteration:
            break

    return Gst.PadProbeReturn.OK


def on_message(bus, message, loop):
    message_type = message.type
    if message_type == Gst.MessageType.EOS:
        print("Received EOS from pipeline", file=sys.stderr)
        loop.quit()
    elif message_type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"Pipeline error: {err}", file=sys.stderr)
        if debug:
            print(f"Debug details: {debug}", file=sys.stderr)
        loop.quit()
    elif message_type == Gst.MessageType.WARNING:
        err, debug = message.parse_warning()
        print(f"Pipeline warning: {err}", file=sys.stderr)
        if debug:
            print(f"Debug details: {debug}", file=sys.stderr)
    return True


def build_pipeline(settings: Settings, writer: MetadataWriter):
    pgie_config = render_pgie_config(settings)

    pipeline = Gst.Pipeline.new("cameraai-deepstream-pipeline")
    if not pipeline:
        raise RuntimeError("Failed to create pipeline")

    source_bin = create_source_bin(0, settings.input_rtsp)
    streammux = make_element("nvstreammux", "streammux")
    pgie = make_element("nvinfer", "primary-inference")
    tracker = make_element("nvtracker", "tracker")
    nvvidconv = make_element("nvvideoconvert", "nvvideo-converter")
    nvosd = make_element("nvdsosd", "nv-onscreendisplay")
    post_osd_convert = make_element("nvvideoconvert", "post-osd-converter")
    capsfilter = make_element("capsfilter", "rtsp-capsfilter")
    encoder = make_element("nvv4l2h264enc", "h264-encoder")
    parser = make_element("h264parse", "h264-parser")
    payloader = make_element("rtph264pay", "rtp-payloader")
    sink = make_element("rtspclientsink", "rtsp-sink")

    streammux.set_property("live-source", 1)
    streammux.set_property("batch-size", 1)
    streammux.set_property("width", settings.output_width)
    streammux.set_property("height", settings.output_height)
    streammux.set_property("batched-push-timeout", 40000)

    pgie.set_property("config-file-path", str(pgie_config))
    apply_tracker_config(tracker, settings.tracker_config)

    capsfilter.set_property(
        "caps",
        Gst.Caps.from_string("video/x-raw(memory:NVMM), format=NV12"),
    )

    encoder.set_property("bitrate", 4000000)
    encoder.set_property("iframeinterval", settings.output_fps)
    encoder.set_property("insert-sps-pps", 1)
    encoder.set_property("preset-level", 1)

    payloader.set_property("pt", 96)
    payloader.set_property("config-interval", 1)

    sink.set_property("location", settings.output_rtsp)
    sink.set_property("latency", 0)

    for element in (
        source_bin,
        streammux,
        pgie,
        tracker,
        nvvidconv,
        nvosd,
        post_osd_convert,
        capsfilter,
        encoder,
        parser,
        payloader,
        sink,
    ):
        pipeline.add(element)

    sinkpad = streammux.request_pad_simple("sink_0")
    if not sinkpad:
        raise RuntimeError("Unable to get sink_0 pad from nvstreammux")
    srcpad = source_bin.get_static_pad("src")
    if not srcpad:
        raise RuntimeError("Unable to get src pad from source bin")
    if srcpad.link(sinkpad) != Gst.PadLinkReturn.OK:
        raise RuntimeError("Failed to link source bin to streammux")

    if not Gst.Element.link_many(
        streammux,
        pgie,
        tracker,
        nvvidconv,
        nvosd,
        post_osd_convert,
        capsfilter,
        encoder,
        parser,
        payloader,
        sink,
    ):
        raise RuntimeError("Failed to link DeepStream pipeline elements")

    osd_sink_pad = nvosd.get_static_pad("sink")
    if not osd_sink_pad:
        raise RuntimeError("Unable to get sink pad for nvdsosd")
    osd_sink_pad.add_probe(Gst.PadProbeType.BUFFER, osd_sink_pad_buffer_probe, writer)

    return pipeline


def apply_tracker_config(tracker, tracker_config_path: Path) -> None:
    parser = ConfigParser()
    parser.read(tracker_config_path, encoding="utf-8")
    if not parser.has_section("tracker"):
        raise ValueError(f"Tracker config missing [tracker] section: {tracker_config_path}")

    for key, raw_value in parser.items("tracker"):
        if tracker.find_property(key) is None:
            print(f"Skipping unsupported tracker property '{key}'", file=sys.stderr)
            continue
        if key == "enable-batch-process" or key == "enable-past-frame" or key == "gpu-id":
            tracker.set_property(key, int(raw_value))
        elif key == "tracker-width" or key == "tracker-height":
            tracker.set_property(key, int(raw_value))
        else:
            tracker.set_property(key, raw_value)


def run() -> int:
    Gst.init(None)
    settings = load_settings()
    writer = MetadataWriter(settings.metadata_path)
    loop = GLib.MainLoop()
    pipeline = None

    def shutdown(*_args):
        loop.quit()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        pipeline = build_pipeline(settings, writer)
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_message, loop)

        print(
            f"Starting pipeline: {settings.input_rtsp} -> {settings.output_rtsp} "
            f"(metadata: {settings.metadata_path})",
            file=sys.stderr,
        )

        pipeline.set_state(Gst.State.PLAYING)
        loop.run()
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"DeepStream configuration failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"DeepStream startup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
        writer.close()


if __name__ == "__main__":
    sys.exit(run())
