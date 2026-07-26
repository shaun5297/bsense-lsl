"""Built-in cross-platform LSL-to-XDF recording backend."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pylsl import StreamInlet, local_clock, resolve_streams

from .live import (
    STREAM_KIND_LABELS,
    SUPPORTED_STREAM_KINDS,
    canonical_stream_kind,
    stream_has_source_id,
)
from .xdf_writer import XDFWriter


Resolver = Callable[[float], Iterable[Any]]
InletFactory = Callable[[Any], Any]


@dataclass
class _RecordedStream:
    stream_id: int
    info: Any
    inlet: Any
    name: str
    channel_count: int
    channel_format: int
    first_timestamp: float = 0.0
    last_timestamp: float = 0.0
    sample_count: int = 0
    clock_offsets: list[tuple[float, float]] = field(default_factory=list)
    clock_offset_failures: int = 0
    timestamp_inversions: int = 0
    previous_timestamp: float | None = None


def _default_inlet_factory(info: Any) -> StreamInlet:
    return StreamInlet(info, max_buflen=360, recover=stream_has_source_id(info))


class EmbeddedRecorderClient:
    """Record one validated BioMultiLite stream set without an external application."""

    def __init__(
        self,
        resolver: Resolver | None = None,
        inlet_factory: InletFactory | None = None,
        required_stream_name: str | None = "BSense Experiment Markers",
        require_biomultilite_streams: bool = True,
        discovery_timeout: float = 3.0,
        offset_interval: float = 5.0,
        offset_retry_interval: float = 1.0,
        offset_timeout: float = 1.0,
        boundary_interval: float = 10.0,
    ) -> None:
        self._resolver = resolver or resolve_streams
        self._inlet_factory = inlet_factory or _default_inlet_factory
        self.required_stream_name = required_stream_name
        self.require_biomultilite_streams = require_biomultilite_streams
        self.discovery_timeout = discovery_timeout
        self.offset_interval = offset_interval
        self.offset_retry_interval = offset_retry_interval
        self.offset_timeout = offset_timeout
        self.boundary_interval = boundary_interval
        self._writer: XDFWriter | None = None
        self._streams: list[_RecordedStream] = []
        self._workers: list[threading.Thread] = []
        self._boundary_worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._errors: list[str] = []
        self._lock = threading.Lock()
        self.diagnostics: list[dict[str, object]] = []

    def _record_diagnostic(self, event: str, **values: object) -> None:
        with self._lock:
            self.diagnostics.append({"unix_time": time.time(), "event": event, **values})

    def _record_error(self, message: str) -> None:
        with self._lock:
            self._errors.append(message)
            self.diagnostics.append({"unix_time": time.time(), "event": "recording_error", "error": message})

    def errors(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._errors)

    @staticmethod
    def _is_marker(info: Any) -> bool:
        return str(info.type()).strip().lower() in {"marker", "markers"}

    @staticmethod
    def _runtime_stream_key(info: Any) -> tuple[str, object]:
        """Identify repeated resolver views without hiding distinct active outlets."""

        try:
            uid = str(info.uid()).strip()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            uid = ""
        if uid:
            return "uid", uid
        # Some test doubles and malformed outlets have no runtime UID. Repeated
        # references to the exact same object are safe to collapse; separate
        # objects remain ambiguous and are rejected by strict selection below.
        return "object", id(info)

    def _deduplicate_resolved_streams(
        self,
        infos: tuple[Any, ...],
    ) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
        unique: list[Any] = []
        duplicates: list[Any] = []
        seen: set[tuple[str, object]] = set()
        for info in infos:
            key = self._runtime_stream_key(info)
            if key in seen:
                duplicates.append(info)
                continue
            seen.add(key)
            unique.append(info)
        return tuple(unique), tuple(duplicates)

    def _select_required_streams(self, infos: tuple[Any, ...]) -> tuple[Any, ...]:
        """Select one deterministic BioMultiLite stream per kind and reject ambiguity."""

        candidates_by_kind: dict[str, list[Any]] = {kind: [] for kind in SUPPORTED_STREAM_KINDS}
        for info in infos:
            kind = canonical_stream_kind(str(info.type()), str(info.name()))
            if kind is not None:
                candidates_by_kind[kind].append(info)

        missing_kinds = [kind for kind, candidates in candidates_by_kind.items() if not candidates]
        if missing_kinds:
            labels = "、".join(STREAM_KIND_LABELS[kind] for kind in missing_kinds)
            raise RuntimeError(f"缺少 BioMultiLite 数值流：{labels}")
        duplicate_kinds = [kind for kind, candidates in candidates_by_kind.items() if len(candidates) > 1]
        if duplicate_kinds:
            labels = "、".join(STREAM_KIND_LABELS[kind] for kind in duplicate_kinds)
            raise RuntimeError(f"发现重复的 BioMultiLite 数值流：{labels}。请只保留一台设备或一组发布流。")

        experiment_markers = (
            [info for info in infos if str(info.name()) == self.required_stream_name]
            if self.required_stream_name is not None
            else []
        )
        other_markers = [info for info in infos if self._is_marker(info) and info not in experiment_markers]
        vendor_markers = [
            info
            for info in other_markers
            if "biomulti" in "".join(character for character in str(info.name()).lower() if character.isalnum())
        ]
        if not vendor_markers and len(other_markers) == 1:
            vendor_markers = other_markers
        if not vendor_markers:
            raise RuntimeError("缺少 BioMultiLite Marker 流")
        if len(vendor_markers) > 1:
            raise RuntimeError("发现多个 BioMultiLite Marker 流，请只保留一台设备或一组发布流。")

        ordered: list[Any] = [
            candidates_by_kind[kind][0]
            for kind in ("eeg", "fnirs", "motion", "metric", "heart_rate")
        ]
        ordered.append(vendor_markers[0])
        ordered.append(candidates_by_kind["general_metric"][0])
        ordered.extend(experiment_markers)
        return tuple(ordered)

    def start_recording(self, output_root: Path, filename: str) -> tuple[Path, int]:
        if self._writer is not None:
            raise RuntimeError("内置录制器已经在运行")
        target_path = output_root.resolve() / filename
        if target_path.exists():
            raise FileExistsError(f"目标 XDF 已存在：{target_path}。请更换 Run 编号。")

        resolved_infos = tuple(self._resolver(self.discovery_timeout))
        if not resolved_infos:
            raise RuntimeError("没有发现任何 LSL 流，无法开始内置 XDF 录制")
        discovered_infos, resolver_duplicates = self._deduplicate_resolved_streams(resolved_infos)
        if self.required_stream_name is not None:
            required_markers = [info for info in discovered_infos if str(info.name()) == self.required_stream_name]
            if not required_markers:
                raise RuntimeError(f"未发现必需的 LSL 流：{self.required_stream_name}")
            if len(required_markers) > 1:
                raise RuntimeError(f"发现多个 {self.required_stream_name} 流，请关闭重复运行的实验程序。")
        infos = self._select_required_streams(discovered_infos) if self.require_biomultilite_streams else discovered_infos
        self._record_diagnostic(
            "stream_inventory",
            discovered_count=len(resolved_infos),
            unique_discovered_count=len(discovered_infos),
            resolver_duplicate_count=len(resolver_duplicates),
            resolver_duplicate_names=[str(info.name()) for info in resolver_duplicates],
            selected_count=len(infos),
            selected_names=[str(info.name()) for info in infos],
        )

        self._stop_event.clear()
        self._errors.clear()
        self._streams.clear()
        self._workers.clear()
        writer = XDFWriter(target_path)
        self._writer = writer
        opened_inlets: list[Any] = []
        try:
            for stream_id, info in enumerate(infos, start=1):
                inlet = self._inlet_factory(info)
                opened_inlets.append(inlet)
                inlet.open_stream(timeout=5.0)
                full_info = inlet.info(timeout=5.0)
                channel_count = int(full_info.channel_count())
                channel_format = int(full_info.channel_format())
                if channel_count <= 0:
                    raise RuntimeError(f"LSL 流 {full_info.name()} 的通道数无效")
                if channel_format not in {1, 2, 3, 4, 5, 6, 7}:
                    raise RuntimeError(f"LSL 流 {full_info.name()} 的数据格式不受支持：{channel_format}")
                writer.write_stream_header(stream_id, full_info.as_xml())
                self._streams.append(
                    _RecordedStream(
                        stream_id=stream_id,
                        info=full_info,
                        inlet=inlet,
                        name=str(full_info.name()),
                        channel_count=channel_count,
                        channel_format=channel_format,
                    )
                )
                self._record_diagnostic(
                    "stream_opened",
                    stream_id=stream_id,
                    name=str(full_info.name()),
                    stream_type=str(full_info.type()),
                    hostname=str(full_info.hostname()),
                    source_id=str(full_info.source_id()),
                    channel_count=channel_count,
                    nominal_srate=float(full_info.nominal_srate()),
                )
        except Exception:
            self._stop_event.set()
            for inlet in opened_inlets:
                try:
                    inlet.close_stream()
                except (AttributeError, RuntimeError):
                    pass
            writer.close()
            self._writer = None
            raise

        for state in self._streams:
            worker = threading.Thread(
                target=self._record_stream,
                args=(state,),
                name=f"xdf-stream-{state.stream_id}",
                daemon=True,
            )
            self._workers.append(worker)
            worker.start()
        self._boundary_worker = threading.Thread(target=self._record_boundaries, name="xdf-boundaries", daemon=True)
        self._boundary_worker.start()
        self._record_diagnostic("recording_started", path=str(target_path), stream_count=len(self._streams))
        return target_path, target_path.stat().st_size

    def _record_stream(self, state: _RecordedStream) -> None:
        assert self._writer is not None
        next_offset = time.monotonic()
        try:
            while not self._stop_event.is_set():
                samples, timestamps = state.inlet.pull_chunk(timeout=0.25, max_samples=4096)
                if timestamps:
                    self._writer.write_samples(
                        state.stream_id,
                        timestamps,
                        samples,
                        state.channel_count,
                        state.channel_format,
                    )
                    if state.sample_count == 0:
                        state.first_timestamp = float(timestamps[0])
                    for timestamp in timestamps:
                        current_timestamp = float(timestamp)
                        if state.previous_timestamp is not None and current_timestamp < state.previous_timestamp:
                            state.timestamp_inversions += 1
                        state.previous_timestamp = current_timestamp
                    state.last_timestamp = float(timestamps[-1])
                    state.sample_count += len(timestamps)
                if time.monotonic() >= next_offset:
                    try:
                        offset = float(state.inlet.time_correction(timeout=self.offset_timeout))
                        now = float(local_clock())
                        collection_time = now - offset
                        self._writer.write_clock_offset(state.stream_id, collection_time, offset)
                        state.clock_offsets.append((collection_time, offset))
                        if state.clock_offset_failures and len(state.clock_offsets) == 1:
                            self._record_diagnostic(
                                "clock_offset_recovered",
                                stream=state.name,
                                failure_count=state.clock_offset_failures,
                            )
                        next_offset = time.monotonic() + self.offset_interval
                    except Exception as error:  # noqa: BLE001 - samples can continue without an offset update
                        state.clock_offset_failures += 1
                        if state.clock_offset_failures == 1 or state.clock_offset_failures % 10 == 0:
                            self._record_diagnostic(
                                "clock_offset_failed",
                                stream=state.name,
                                failure_count=state.clock_offset_failures,
                                error=str(error),
                            )
                        next_offset = time.monotonic() + self.offset_retry_interval
        except Exception as error:  # noqa: BLE001 - reported when the recording is finalized
            self._record_error(f"{state.name}: {error}")

    def _record_boundaries(self) -> None:
        assert self._writer is not None
        while not self._stop_event.wait(self.boundary_interval):
            try:
                self._writer.write_boundary()
            except Exception as error:  # noqa: BLE001 - reported when the recording is finalized
                self._record_error(f"XDF boundary: {error}")
                return

    def stop_recording(self, target_path: Path | None = None) -> int | None:
        writer = self._writer
        if writer is None:
            raise RuntimeError("内置录制器尚未启动")
        self._stop_event.set()
        for state, worker in zip(self._streams, self._workers, strict=True):
            worker.join(timeout=3.0)
            if worker.is_alive():
                try:
                    state.inlet.close_stream()
                except (AttributeError, RuntimeError):
                    pass
                worker.join(timeout=2.0)
                if worker.is_alive():
                    self._record_error(f"录制线程未按时停止：{worker.name}")
        if self._boundary_worker is not None:
            self._boundary_worker.join(timeout=1.0)

        try:
            for state in self._streams:
                writer.write_stream_footer(
                    state.stream_id,
                    state.first_timestamp,
                    state.last_timestamp,
                    state.sample_count,
                    state.clock_offsets,
                )
                self._record_diagnostic(
                    "stream_closed",
                    stream_id=state.stream_id,
                    name=state.name,
                    sample_count=state.sample_count,
                    first_timestamp=state.first_timestamp,
                    last_timestamp=state.last_timestamp,
                    observed_srate=(
                        (state.sample_count - 1) / (state.last_timestamp - state.first_timestamp)
                        if state.sample_count > 1 and state.last_timestamp > state.first_timestamp
                        else None
                    ),
                    clock_offset_count=len(state.clock_offsets),
                    clock_offset_failures=state.clock_offset_failures,
                    timestamp_inversions=state.timestamp_inversions,
                )
        finally:
            for state in self._streams:
                try:
                    state.inlet.close_stream()
                except (AttributeError, RuntimeError):
                    pass
            writer.close()
            self._writer = None

        path = target_path or writer.path
        final_size = path.stat().st_size
        self._record_diagnostic("recording_stopped", path=str(path), size_bytes=final_size)
        if self._errors:
            raise RuntimeError("；".join(self._errors))
        return final_size

    def write_diagnostics(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            records = tuple(self.diagnostics)
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
