import io
import struct
import tempfile
import time
import unittest
from pathlib import Path

from pylsl import StreamInfo, cf_float32, cf_string

from bsense_experiment.embedded_recorder import EmbeddedRecorderClient
from bsense_experiment.xdf_writer import (
    BOUNDARY,
    CLOCK_OFFSET,
    FILE_HEADER,
    SAMPLES,
    STREAM_FOOTER,
    STREAM_HEADER,
    XDFWriter,
    encode_varlen_int,
)


def read_varlen_int(handle: io.BufferedReader) -> int | None:
    width_raw = handle.read(1)
    if not width_raw:
        return None
    width = width_raw[0]
    if width not in {1, 4, 8}:
        raise ValueError(f"invalid variable integer width: {width}")
    return int.from_bytes(handle.read(width), "little")


def read_chunks(path: Path) -> list[tuple[int, int | None, bytes]]:
    chunks: list[tuple[int, int | None, bytes]] = []
    with path.open("rb") as handle:
        if handle.read(4) != b"XDF:":
            raise ValueError("missing XDF magic")
        while (chunk_length := read_varlen_int(handle)) is not None:
            raw = handle.read(chunk_length)
            if len(raw) != chunk_length:
                raise ValueError("truncated XDF chunk")
            tag = struct.unpack("<H", raw[:2])[0]
            if tag in {STREAM_HEADER, SAMPLES, CLOCK_OFFSET, STREAM_FOOTER}:
                stream_id = struct.unpack("<I", raw[2:6])[0]
                content = raw[6:]
            else:
                stream_id = None
                content = raw[2:]
            chunks.append((tag, stream_id, content))
    return chunks


class FakeInlet:
    def __init__(self, info: StreamInfo) -> None:
        self._info = info
        self._delivered = False

    def open_stream(self, timeout: float) -> None:
        del timeout

    def info(self, timeout: float) -> StreamInfo:
        del timeout
        return self._info

    def pull_chunk(self, timeout: float, max_samples: int) -> tuple[list[list[object]], list[float]]:
        del max_samples
        if not self._delivered:
            self._delivered = True
            if self._info.channel_format() == cf_string:
                return [["marker"]], [10.0]
            channel_count = self._info.channel_count()
            return (
                [[float(index) for index in range(channel_count)] for _ in range(2)],
                [10.0, 10.01],
            )
        time.sleep(min(timeout, 0.01))
        return [], []

    def time_correction(self, timeout: float) -> float:
        del timeout
        return 0.001

    def close_stream(self) -> None:
        return None


class FlakyOffsetInlet(FakeInlet):
    def __init__(self, info: StreamInfo) -> None:
        super().__init__(info)
        self._offset_calls = 0

    def time_correction(self, timeout: float) -> float:
        del timeout
        self._offset_calls += 1
        if self._offset_calls == 1:
            raise RuntimeError("temporary timeout")
        return 0.001


class InvertingTimestampInlet(FakeInlet):
    def pull_chunk(self, timeout: float, max_samples: int) -> tuple[list[list[object]], list[float]]:
        samples, timestamps = super().pull_chunk(timeout, max_samples)
        if samples and self._info.channel_format() != cf_string:
            return samples, [10.0, 9.99]
        return samples, timestamps


class XDFWriterTests(unittest.TestCase):
    def test_varlen_integer_boundaries(self) -> None:
        self.assertEqual(encode_varlen_int(255), b"\x01\xff")
        self.assertEqual(encode_varlen_int(256), b"\x04\x00\x01\x00\x00")

    def test_writer_emits_all_required_chunk_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "writer.xdf"
            writer = XDFWriter(path)
            writer.write_stream_header(1, "<info><name>EEG</name></info>")
            writer.write_samples(1, [1.0], [[1.5, -2.0]], 2, cf_float32)
            writer.write_clock_offset(1, 1.0, 0.001)
            writer.write_boundary()
            writer.write_stream_footer(1, 1.0, 1.0, 1)
            writer.close()

            chunks = read_chunks(path)
            self.assertEqual([chunk[0] for chunk in chunks], [FILE_HEADER, STREAM_HEADER, SAMPLES, CLOCK_OFFSET, BOUNDARY, STREAM_FOOTER])
            sample_payload = chunks[2][2]
            self.assertEqual(sample_payload[:5], b"\x04\x01\x00\x00\x00")
            self.assertEqual(sample_payload[5], 8)
            self.assertEqual(struct.unpack("<d", sample_payload[6:14])[0], 1.0)
            self.assertEqual(struct.unpack("<ff", sample_payload[14:22]), (1.5, -2.0))

    def test_embedded_recorder_captures_numeric_and_marker_streams(self) -> None:
        marker = StreamInfo("BSense Experiment Markers", "Markers", 1, 0.0, cf_string, "marker-source")
        eeg = StreamInfo("BioMultiLite EEG", "EEG", 2, 100.0, cf_float32, "eeg-source")
        infos = (marker, eeg)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = EmbeddedRecorderClient(
                resolver=lambda _timeout: infos,
                inlet_factory=FakeInlet,
                require_biomultilite_streams=False,
                offset_interval=0.01,
                boundary_interval=0.01,
            )
            path, initial_size = client.start_recording(root, "recording.xdf")
            time.sleep(0.06)
            final_size = client.stop_recording(path)

            self.assertGreater(initial_size, 4)
            self.assertIsNotNone(final_size)
            self.assertGreater(final_size or 0, initial_size)
            chunks = read_chunks(path)
            tags = [chunk[0] for chunk in chunks]
            self.assertEqual(tags.count(STREAM_HEADER), 2)
            self.assertGreaterEqual(tags.count(SAMPLES), 2)
            self.assertEqual(tags.count(STREAM_FOOTER), 2)
            self.assertIn(BOUNDARY, tags)
            self.assertTrue(any(record["event"] == "recording_started" for record in client.diagnostics))
            self.assertTrue(any(record["event"] == "recording_stopped" for record in client.diagnostics))

    def test_embedded_recorder_retries_clock_offsets_and_reports_recovery(self) -> None:
        marker = StreamInfo("BSense Experiment Markers", "Markers", 1, 0.0, cf_string, "marker-source")
        eeg = StreamInfo("BioMultiLite EEG", "EEG", 2, 100.0, cf_float32, "eeg-source")
        with tempfile.TemporaryDirectory() as directory:
            client = EmbeddedRecorderClient(
                resolver=lambda _timeout: (marker, eeg),
                inlet_factory=FlakyOffsetInlet,
                require_biomultilite_streams=False,
                offset_interval=0.01,
                offset_retry_interval=0.005,
            )
            path, _ = client.start_recording(Path(directory), "clock-retry.xdf")
            time.sleep(0.06)
            client.stop_recording(path)

        recovered = [record for record in client.diagnostics if record["event"] == "clock_offset_recovered"]
        self.assertEqual(len(recovered), 2)
        closed = [record for record in client.diagnostics if record["event"] == "stream_closed"]
        self.assertTrue(all(record["clock_offset_count"] >= 1 for record in closed))
        self.assertTrue(all(record["clock_offset_failures"] == 1 for record in closed))

    def test_embedded_recorder_reports_raw_timestamp_inversions(self) -> None:
        marker = StreamInfo("BSense Experiment Markers", "Markers", 1, 0.0, cf_string, "marker-source")
        eeg = StreamInfo("BioMultiLite EEG", "EEG", 2, 100.0, cf_float32, "eeg-source")
        with tempfile.TemporaryDirectory() as directory:
            client = EmbeddedRecorderClient(
                resolver=lambda _timeout: (marker, eeg),
                inlet_factory=InvertingTimestampInlet,
                require_biomultilite_streams=False,
                offset_interval=0.01,
            )
            path, _ = client.start_recording(Path(directory), "timestamp-inversion.xdf")
            time.sleep(0.03)
            client.stop_recording(path)

        eeg_closed = next(
            record
            for record in client.diagnostics
            if record["event"] == "stream_closed" and record["name"] == "BioMultiLite EEG"
        )
        self.assertEqual(eeg_closed["timestamp_inversions"], 1)

    def test_embedded_recorder_requires_experiment_marker(self) -> None:
        eeg = StreamInfo("BioMultiLite EEG", "EEG", 2, 100.0, cf_float32, "eeg-source")
        client = EmbeddedRecorderClient(
            resolver=lambda _timeout: (eeg,),
            inlet_factory=FakeInlet,
            require_biomultilite_streams=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "BSense Experiment Markers"):
                client.start_recording(Path(directory), "recording.xdf")

    def test_embedded_recorder_requires_biomultilite_marker(self) -> None:
        stream_types = ("EEG", "FNIRS", "Motion", "Metric", "Heart Rate", "General Metric")
        infos = tuple(
            StreamInfo(f"BioMultiLite {stream_type}", stream_type, 1, 10.0, cf_float32, f"source-{index}")
            for index, stream_type in enumerate(stream_types)
        ) + (StreamInfo("BSense Experiment Markers", "Markers", 1, 0.0, cf_string, "experiment-marker"),)
        client = EmbeddedRecorderClient(resolver=lambda _timeout: infos, inlet_factory=FakeInlet)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "BioMultiLite Marker"):
                client.start_recording(Path(directory), "recording.xdf")

    @staticmethod
    def _required_infos() -> tuple[StreamInfo, ...]:
        definitions = (
            ("BioMultiLite EEG", "EEG", 2),
            ("BioMultiLite FNIRS", "FNIRS", 16),
            ("BioMultiLite Motion", "Motion", 6),
            ("BioMultiLite Metric", "Metric", 2),
            ("BioMultiLite Heart Rate", "Heart Rate", 1),
            ("BioMultiLite General Metric", "General Metric", 13),
        )
        numeric = tuple(
            StreamInfo(name, stream_type, channels, 10.0, cf_float32, f"source-{index}")
            for index, (name, stream_type, channels) in enumerate(definitions)
        )
        markers = (
            StreamInfo("BioMultiLite Marker", "Markers", 1, 0.0, cf_string, "vendor-marker"),
            StreamInfo("BSense Experiment Markers", "Markers", 1, 0.0, cf_string, "experiment-marker"),
        )
        return numeric + markers

    def test_strict_stream_selection_excludes_unrelated_streams(self) -> None:
        required = self._required_infos()
        unrelated = StreamInfo("Other Sensor", "Temperature", 1, 1.0, cf_float32, "other")
        client = EmbeddedRecorderClient()

        selected = client._select_required_streams(required + (unrelated,))

        self.assertEqual(len(selected), 8)
        self.assertNotIn(unrelated, selected)
        self.assertEqual([info.name() for info in selected][-2:], ["BioMultiLite General Metric", "BSense Experiment Markers"])

    def test_strict_stream_selection_rejects_duplicate_numeric_kind(self) -> None:
        required = self._required_infos()
        duplicate_eeg = StreamInfo("Backup EEG", "EEG", 2, 250.0, cf_float32, "backup-eeg")
        client = EmbeddedRecorderClient()

        with self.assertRaisesRegex(RuntimeError, "重复.*EEG"):
            client._select_required_streams(required + (duplicate_eeg,))


if __name__ == "__main__":
    unittest.main()
