"""Thread-safe real-time access to BioMultiLite LSL streams.

The classes in this module deliberately do not depend on a GUI.  A future
classifier can consume the same :class:`DataWindow` objects used by the live
monitor while the built-in recorder captures the streams independently.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence


SUPPORTED_STREAM_KINDS = (
    "eeg",
    "fnirs",
    "motion",
    "metric",
    "heart_rate",
    "general_metric",
)

STREAM_KIND_LABELS = {
    "eeg": "EEG",
    "fnirs": "fNIRS",
    "motion": "Motion",
    "metric": "Metric",
    "heart_rate": "Heart Rate",
    "general_metric": "General Metric",
}


def _normalize_stream_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def canonical_stream_kind(stream_type: str, stream_name: str = "") -> str | None:
    """Map vendor spelling variants to stable application stream kinds."""

    candidates = {_normalize_stream_text(stream_type), _normalize_stream_text(stream_name)}
    aliases = (
        ("general_metric", {"generalmetric", "generalmetrics"}),
        ("heart_rate", {"heartrate", "hr"}),
        ("fnirs", {"fnirs", "nir", "nirs", "ir"}),
        ("motion", {"motion", "imu"}),
        ("metric", {"metric", "metrics"}),
        ("eeg", {"eeg"}),
    )
    for kind, values in aliases:
        if candidates.intersection(values):
            return kind
    return None


@dataclass(frozen=True)
class StreamDescriptor:
    """Stable stream metadata exposed to the UI and inference code."""

    kind: str
    name: str
    stream_type: str
    channel_count: int
    nominal_srate: float
    channel_labels: tuple[str, ...]
    source_id: str


@dataclass(frozen=True)
class DataWindow:
    """An immutable time-aligned slice of one LSL stream."""

    descriptor: StreamDescriptor
    timestamps: tuple[float, ...]
    samples: tuple[tuple[float, ...], ...]
    total_samples_received: int
    last_received_monotonic: float | None

    @property
    def is_live(self) -> bool:
        return self.last_received_monotonic is not None and time.monotonic() - self.last_received_monotonic < 2.5

    @property
    def duration(self) -> float:
        if len(self.timestamps) < 2:
            return 0.0
        return max(0.0, self.timestamps[-1] - self.timestamps[0])

    @property
    def observed_srate(self) -> float | None:
        if self.duration <= 0:
            return None
        return (len(self.timestamps) - 1) / self.duration


class StreamBuffer:
    """Bounded, thread-safe LSL sample buffer."""

    def __init__(self, descriptor: StreamDescriptor, buffer_seconds: float = 60.0) -> None:
        if buffer_seconds <= 0:
            raise ValueError("buffer_seconds must be positive")
        self.descriptor = descriptor
        rate = descriptor.nominal_srate if descriptor.nominal_srate > 0 else 100.0
        max_samples = min(max(math.ceil(rate * buffer_seconds * 1.25), 2048), 250_000)
        self._timestamps: deque[float] = deque(maxlen=max_samples)
        self._samples: deque[tuple[float, ...]] = deque(maxlen=max_samples)
        self._lock = threading.Lock()
        self._total_samples_received = 0
        self._last_received_monotonic: float | None = None

    def append_chunk(self, samples: Sequence[Sequence[float]], timestamps: Sequence[float]) -> int:
        """Append valid timestamped rows and return the accepted row count."""

        accepted: list[tuple[float, tuple[float, ...]]] = []
        for timestamp, sample in zip(timestamps, samples, strict=False):
            if len(sample) != self.descriptor.channel_count:
                continue
            try:
                row = tuple(float(value) for value in sample)
                accepted.append((float(timestamp), row))
            except (TypeError, ValueError):
                continue
        if not accepted:
            return 0
        with self._lock:
            for timestamp, row in accepted:
                self._timestamps.append(timestamp)
                self._samples.append(row)
            self._total_samples_received += len(accepted)
            self._last_received_monotonic = time.monotonic()
        return len(accepted)

    def window(self, seconds: float, max_points: int | None = None) -> DataWindow:
        """Return the newest ``seconds`` of data, optionally display-decimated."""

        if seconds <= 0:
            raise ValueError("seconds must be positive")
        if max_points is not None and max_points <= 1:
            raise ValueError("max_points must be greater than one")
        with self._lock:
            timestamps = tuple(self._timestamps)
            samples = tuple(self._samples)
            total = self._total_samples_received
            last_received = self._last_received_monotonic
        if timestamps:
            cutoff = timestamps[-1] - seconds
            start = 0
            while start < len(timestamps) and timestamps[start] < cutoff:
                start += 1
            timestamps = timestamps[start:]
            samples = samples[start:]
        if max_points is not None and len(timestamps) > max_points:
            step = math.ceil((len(timestamps) - 1) / (max_points - 1))
            indexes = list(range(0, len(timestamps), step))
            if indexes[-1] != len(timestamps) - 1:
                indexes.append(len(timestamps) - 1)
            timestamps = tuple(timestamps[index] for index in indexes)
            samples = tuple(samples[index] for index in indexes)
        return DataWindow(
            descriptor=self.descriptor,
            timestamps=timestamps,
            samples=samples,
            total_samples_received=total,
            last_received_monotonic=last_received,
        )


def _safe_info_value(info: Any, method_name: str, default: Any) -> Any:
    try:
        return getattr(info, method_name)()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return default


def stream_has_source_id(info: Any) -> bool:
    """Return whether liblsl can recover this stream after its outlet restarts."""

    return bool(str(_safe_info_value(info, "source_id", "")).strip())


def _fallback_channel_labels(kind: str, channel_count: int) -> tuple[str, ...]:
    known_labels = {
        "eeg": ("Fp1", "Fp2"),
        "fnirs": (
            "S1D1 · 735nm",
            "S1D2 · 735nm",
            "S1D3 · 735nm",
            "S1D4 · 735nm",
            "S2D5 · 735nm",
            "S2D6 · 735nm",
            "S2D7 · 735nm",
            "S2D8 · 735nm",
            "S1D1 · 850nm",
            "S1D2 · 850nm",
            "S1D3 · 850nm",
            "S1D4 · 850nm",
            "S2D5 · 850nm",
            "S2D6 · 850nm",
            "S2D7 · 850nm",
            "S2D8 · 850nm",
        ),
        "motion": ("Accel X", "Accel Y", "Accel Z", "Gyro X", "Gyro Y", "Gyro Z"),
        "metric": ("Metric 1", "Metric 2"),
        "heart_rate": ("Heart Rate",),
    }.get(kind, ())
    if kind == "general_metric":
        return tuple(f"通用指标 {index + 1}" for index in range(channel_count))
    return tuple(known_labels[index] if index < len(known_labels) else f"Ch{index + 1}" for index in range(channel_count))


def _channel_labels(info: Any, kind: str, channel_count: int) -> tuple[str, ...]:
    labels: list[str] = []
    try:
        channel = info.desc().child("channels").child("channel")
        for index in range(channel_count):
            if channel.empty():
                break
            label = channel.child_value("label").strip()
            labels.append(label or f"Ch{index + 1}")
            channel = channel.next_sibling()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        labels = []
    fallback = _fallback_channel_labels(kind, channel_count)
    labels.extend(fallback[index] for index in range(len(labels), channel_count))
    return tuple(labels)


def describe_stream(info: Any) -> StreamDescriptor | None:
    """Build normalized metadata from a pylsl ``StreamInfo`` object."""

    name = str(_safe_info_value(info, "name", ""))
    stream_type = str(_safe_info_value(info, "type", ""))
    kind = canonical_stream_kind(stream_type, name)
    if kind not in SUPPORTED_STREAM_KINDS:
        return None
    channel_count = int(_safe_info_value(info, "channel_count", 0))
    if channel_count <= 0:
        return None
    nominal_srate = float(_safe_info_value(info, "nominal_srate", 0.0))
    source_id = str(_safe_info_value(info, "source_id", ""))
    return StreamDescriptor(
        kind=kind,
        name=name or STREAM_KIND_LABELS[kind],
        stream_type=stream_type or STREAM_KIND_LABELS[kind],
        channel_count=channel_count,
        nominal_srate=nominal_srate,
        channel_labels=_channel_labels(info, kind, channel_count),
        source_id=source_id,
    )


Resolver = Callable[[float], Iterable[Any]]
InletFactory = Callable[[Any, float], Any]


def _default_resolver(timeout: float) -> Iterable[Any]:
    from pylsl import resolve_streams

    return resolve_streams(timeout)


def _default_inlet_factory(info: Any, buffer_seconds: float) -> Any:
    from pylsl import StreamInlet, proc_clocksync, proc_dejitter, proc_monotonize

    processing_flags = proc_clocksync | proc_dejitter | proc_monotonize
    return StreamInlet(
        info,
        max_buflen=max(1, math.ceil(buffer_seconds)),
        recover=stream_has_source_id(info),
        processing_flags=processing_flags,
    )


class _StreamWorker(threading.Thread):
    def __init__(
        self,
        info: Any,
        buffer: StreamBuffer,
        buffer_seconds: float,
        inlet_factory: InletFactory,
        on_stopped: Callable[[str, str | None], None],
    ) -> None:
        super().__init__(name=f"lsl-{buffer.descriptor.kind}", daemon=True)
        self.info = info
        self.buffer = buffer
        self.buffer_seconds = buffer_seconds
        self.inlet_factory = inlet_factory
        self.on_stopped = on_stopped
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        inlet = None
        error: str | None = None
        try:
            inlet = self.inlet_factory(self.info, self.buffer_seconds)
            while not self.stop_event.is_set():
                samples, timestamps = inlet.pull_chunk(timeout=0.25, max_samples=1024)
                if timestamps:
                    self.buffer.append_chunk(samples, timestamps)
        except Exception as caught:  # noqa: BLE001 - the manager reconnects and exposes the error
            error = str(caught)
        finally:
            if inlet is not None:
                try:
                    inlet.close_stream()
                except (AttributeError, RuntimeError):
                    pass
            self.on_stopped(self.buffer.descriptor.kind, error)


class LiveStreamManager:
    """Discover BioMultiLite outlets and maintain one live buffer per data kind."""

    def __init__(
        self,
        buffer_seconds: float = 60.0,
        resolver: Resolver | None = None,
        inlet_factory: InletFactory | None = None,
    ) -> None:
        self.buffer_seconds = buffer_seconds
        self._resolver = resolver or _default_resolver
        self._inlet_factory = inlet_factory or _default_inlet_factory
        self._buffers: dict[str, StreamBuffer] = {}
        self._workers: dict[str, _StreamWorker] = {}
        self._errors: dict[str, str] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._refresh_event = threading.Event()
        self._discovery_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._discovery_thread is not None and self._discovery_thread.is_alive():
            return
        self._stop_event.clear()
        self._discovery_thread = threading.Thread(target=self._discovery_loop, name="lsl-discovery", daemon=True)
        self._discovery_thread.start()

    def refresh(self) -> None:
        self._refresh_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._refresh_event.set()
        with self._lock:
            workers = tuple(self._workers.values())
        for worker in workers:
            worker.stop()
        if self._discovery_thread is not None:
            self._discovery_thread.join(timeout=2.0)
        for worker in workers:
            worker.join(timeout=1.0)

    def _discovery_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                stream_infos = tuple(self._resolver(1.0))
                self._connect_new_streams(stream_infos)
                with self._lock:
                    self._errors.pop("discovery", None)
            except Exception as caught:  # noqa: BLE001 - discovery must remain retryable
                with self._lock:
                    self._errors["discovery"] = str(caught)
            self._refresh_event.wait(timeout=2.0)
            self._refresh_event.clear()

    def _connect_new_streams(self, stream_infos: Iterable[Any]) -> None:
        for info in stream_infos:
            if self._stop_event.is_set():
                return
            descriptor = describe_stream(info)
            if descriptor is None:
                continue
            with self._lock:
                current_worker = self._workers.get(descriptor.kind)
                if current_worker is not None and current_worker.is_alive():
                    continue
                buffer = self._buffers.get(descriptor.kind)
                if buffer is None or buffer.descriptor != descriptor:
                    buffer = StreamBuffer(descriptor, self.buffer_seconds)
                    self._buffers[descriptor.kind] = buffer
                worker = _StreamWorker(
                    info,
                    buffer,
                    self.buffer_seconds,
                    self._inlet_factory,
                    self._worker_stopped,
                )
                self._workers[descriptor.kind] = worker
                self._errors.pop(descriptor.kind, None)
            worker.start()

    def _worker_stopped(self, kind: str, error: str | None) -> None:
        if error:
            with self._lock:
                self._errors[kind] = error
        if not self._stop_event.is_set():
            self._refresh_event.set()

    def window(self, kind: str, seconds: float, max_points: int | None = None) -> DataWindow | None:
        """Return a model-ready or display-decimated window for ``kind``."""

        with self._lock:
            buffer = self._buffers.get(kind)
        return buffer.window(seconds, max_points=max_points) if buffer is not None else None

    def descriptors(self) -> tuple[StreamDescriptor, ...]:
        with self._lock:
            return tuple(buffer.descriptor for buffer in self._buffers.values())

    def errors(self) -> dict[str, str]:
        with self._lock:
            return dict(self._errors)
