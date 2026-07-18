import time
import unittest
from unittest.mock import patch

from bsense_experiment.live import (
    DataWindow,
    LiveStreamManager,
    StreamBuffer,
    StreamDescriptor,
    _fallback_channel_labels,
    _default_inlet_factory,
    canonical_stream_kind,
    describe_stream,
)


class FakeInfo:
    def name(self) -> str:
        return "BioMulti Lite EEG"

    def type(self) -> str:
        return "EEG"

    def channel_count(self) -> int:
        return 2

    def nominal_srate(self) -> float:
        return 250.0

    def source_id(self) -> str:
        return "device-eeg"

    def desc(self):
        raise RuntimeError("test metadata omitted")


class FakeInlet:
    def __init__(self) -> None:
        self.sent = False

    def pull_chunk(self, timeout: float, max_samples: int):
        if not self.sent:
            self.sent = True
            return [[1.0, 2.0], [3.0, 4.0]], [10.0, 10.004]
        time.sleep(min(timeout, 0.01))
        return [], []

    def close_stream(self) -> None:
        pass


class LiveStreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.descriptor = StreamDescriptor(
            kind="eeg",
            name="BioMulti Lite EEG",
            stream_type="EEG",
            channel_count=2,
            nominal_srate=250.0,
            channel_labels=("Fp1", "Fp2"),
            source_id="device-eeg",
        )

    def test_vendor_stream_names_are_normalized(self) -> None:
        self.assertEqual(canonical_stream_kind("EEG"), "eeg")
        self.assertEqual(canonical_stream_kind("FNIRS"), "fnirs")
        self.assertEqual(canonical_stream_kind("HeartRate"), "heart_rate")
        self.assertEqual(canonical_stream_kind("General Metric"), "general_metric")
        self.assertEqual(canonical_stream_kind("Metric", "General Metric"), "general_metric")
        self.assertIsNone(canonical_stream_kind("Markers"))

    def test_stream_descriptor_uses_known_vendor_channel_labels(self) -> None:
        descriptor = describe_stream(FakeInfo())
        self.assertIsNotNone(descriptor)
        assert descriptor is not None
        self.assertEqual(descriptor.channel_labels, ("Fp1", "Fp2"))
        self.assertEqual(descriptor.nominal_srate, 250.0)

    def test_buffer_returns_latest_model_ready_window(self) -> None:
        buffer = StreamBuffer(self.descriptor, buffer_seconds=10.0)
        timestamps = [index / 10 for index in range(51)]
        samples = [[float(index), -float(index)] for index in range(51)]
        accepted = buffer.append_chunk(samples, timestamps)

        window = buffer.window(2.0)

        self.assertEqual(accepted, 51)
        self.assertEqual(window.timestamps[0], 3.0)
        self.assertEqual(window.timestamps[-1], 5.0)
        self.assertEqual(window.samples[-1], (50.0, -50.0))
        self.assertEqual(window.total_samples_received, 51)
        self.assertTrue(window.is_live)
        self.assertAlmostEqual(window.duration, 2.0)
        self.assertAlmostEqual(window.observed_srate or 0.0, 10.0)

    def test_display_decimation_keeps_newest_sample(self) -> None:
        buffer = StreamBuffer(self.descriptor)
        timestamps = [index / 250 for index in range(1000)]
        samples = [[float(index), float(index)] for index in range(1000)]
        buffer.append_chunk(samples, timestamps)

        window = buffer.window(10.0, max_points=100)

        self.assertLessEqual(len(window.samples), 101)
        self.assertEqual(window.timestamps[-1], timestamps[-1])
        self.assertEqual(window.samples[-1][0], 999.0)

    def test_invalid_rows_are_ignored(self) -> None:
        buffer = StreamBuffer(self.descriptor)
        accepted = buffer.append_chunk([[1.0], [2.0, 3.0]], [time.time(), time.time()])
        self.assertEqual(accepted, 1)
        self.assertEqual(buffer.window(1.0).samples, ((2.0, 3.0),))

    def test_manager_discovers_and_buffers_without_gui(self) -> None:
        manager = LiveStreamManager(
            resolver=lambda _timeout: [FakeInfo()],
            inlet_factory=lambda _info, _seconds: FakeInlet(),
        )
        manager.start()
        try:
            deadline = time.monotonic() + 1.0
            window = manager.window("eeg", 1.0)
            while (window is None or len(window.samples) < 2) and time.monotonic() < deadline:
                time.sleep(0.01)
                window = manager.window("eeg", 1.0)
            self.assertIsNotNone(window)
            assert window is not None
            self.assertEqual(window.samples, ((1.0, 2.0), (3.0, 4.0)))
        finally:
            manager.stop()

    def test_default_inlet_uses_integer_buffer_length(self) -> None:
        from pylsl import proc_clocksync, proc_dejitter, proc_monotonize

        info = object()
        with patch("pylsl.StreamInlet") as inlet_class:
            _default_inlet_factory(info, 60.0)
        inlet_class.assert_called_once_with(
            info,
            max_buflen=60,
            recover=True,
            processing_flags=proc_clocksync | proc_dejitter | proc_monotonize,
        )

    def test_general_metric_fallback_labels_do_not_claim_unknown_semantics(self) -> None:
        self.assertEqual(
            _fallback_channel_labels("general_metric", 3),
            ("通用指标 1", "通用指标 2", "通用指标 3"),
        )

    def test_empty_window_has_no_observed_rate(self) -> None:
        window = DataWindow(self.descriptor, (), (), 0, None)

        self.assertEqual(window.duration, 0.0)
        self.assertIsNone(window.observed_srate)


if __name__ == "__main__":
    unittest.main()
