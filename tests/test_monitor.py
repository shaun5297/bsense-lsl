import math
import time
import unittest

from bsense_experiment.live import DataWindow, StreamDescriptor
from bsense_experiment.monitor import (
    center_signal,
    effective_sample_rate,
    eeg_band_coverage,
    eeg_periodogram,
    relative_band_powers,
    robust_limits,
    stream_rate_text,
)


class MonitorSignalTests(unittest.TestCase):
    @staticmethod
    def _window(kind: str, nominal_srate: float, timestamps: tuple[float, ...]) -> DataWindow:
        descriptor = StreamDescriptor(kind, kind, kind, 1, nominal_srate, ("value",), "")
        return DataWindow(
            descriptor=descriptor,
            timestamps=timestamps,
            samples=tuple((0.0,) for _ in timestamps),
            total_samples_received=len(timestamps),
            last_received_monotonic=time.monotonic(),
        )

    def test_robust_limits_ignore_single_large_outlier(self) -> None:
        low, high = robust_limits([*range(100), 1_000_000.0])

        self.assertLess(low, 5.0)
        self.assertLess(high, 150.0)

    def test_center_signal_removes_large_dc_offset(self) -> None:
        centered = center_signal([100_001.0, 100_002.0, 100_003.0])

        self.assertAlmostEqual(sum(centered), 0.0)
        self.assertEqual(centered, (-1.0, 0.0, 1.0))

    def test_eeg_periodogram_finds_alpha_peak(self) -> None:
        sample_rate = 250.0
        values = [math.sin(2.0 * math.pi * 10.0 * index / sample_rate) for index in range(512)]

        frequencies, powers = eeg_periodogram(values, sample_rate)
        peak_frequency = frequencies[max(range(len(powers)), key=powers.__getitem__)]
        bands = relative_band_powers(frequencies, powers)

        self.assertAlmostEqual(peak_frequency, 10.0, delta=0.6)
        self.assertEqual(max(range(len(bands)), key=bands.__getitem__), 2)

    def test_rate_text_exposes_large_metadata_mismatch(self) -> None:
        timestamps = tuple(index * 0.04 for index in range(76))

        text = stream_rate_text(self._window("metric", 250.0, timestamps))

        self.assertEqual(text, "实测 25.0 Hz（元数据 250 Hz）")

    def test_rate_text_uses_observed_rate_when_it_matches_metadata(self) -> None:
        timestamps = tuple(index / 250.0 for index in range(751))

        text = stream_rate_text(self._window("eeg", 250.0, timestamps))

        self.assertEqual(text, "实测 250.0 Hz")

    def test_spectral_analysis_prefers_stable_observed_rate(self) -> None:
        timestamps = tuple(index * 0.04 for index in range(76))

        rate = effective_sample_rate(self._window("eeg", 250.0, timestamps))

        self.assertAlmostEqual(rate, 25.0)

    def test_low_rate_eeg_marks_unobservable_bands(self) -> None:
        self.assertEqual(
            eeg_band_coverage(12.5),
            ("full", "full", "partial", "none", "none"),
        )


if __name__ == "__main__":
    unittest.main()
