"""Tkinter live monitor for BioMultiLite LSL streams."""

from __future__ import annotations

import math
import time
from tkinter import BooleanVar, Canvas, StringVar, Tk, Toplevel, ttk
from typing import Any, Iterable, Sequence

from .live import DataWindow, LiveStreamManager, STREAM_KIND_LABELS, SUPPORTED_STREAM_KINDS
from .platform_support import ui_font_family


UI_FONT_FAMILY = ui_font_family()
BACKGROUND = "#F7F9FC"
PANEL_BACKGROUND = "#FFFFFF"
GRID_COLOR = "#E9EDF3"
AXIS_COLOR = "#7A8494"
TEXT_COLOR = "#253044"
MUTED_COLOR = "#667085"
LIVE_COLOR = "#12A150"
PLOT_COLORS = ("#5B8FF9", "#61DDAA", "#F6BD16", "#E8684A", "#6DC8EC", "#9270CA", "#FF9D4D", "#269A99")
WAVELENGTH_COLORS = ("#FF6B5E", "#5B8FF9")
MOTION_COLORS = ("#E64B35", "#F0B429", "#4C78FF")
EEG_BANDS = (
    ("DELTA", 1.5, 4.0, "#E8684A"),
    ("THETA", 4.0, 8.0, "#F6BD16"),
    ("ALPHA", 8.0, 13.0, "#61A58B"),
    ("BETA", 13.0, 25.0, "#5B8FF9"),
    ("GAMMA", 25.0, 45.0, "#9270CA"),
)


def _finite(values: Iterable[float]) -> list[float]:
    return [float(value) for value in values if math.isfinite(value)]


def _quantile(sorted_values: Sequence[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    position = max(0.0, min(1.0, fraction)) * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def robust_limits(values: Iterable[float]) -> tuple[float, float]:
    """Return outlier-resistant plot limits with enough room for flat signals."""

    finite_values = sorted(_finite(values))
    if not finite_values:
        return -1.0, 1.0
    low = _quantile(finite_values, 0.02)
    high = _quantile(finite_values, 0.98)
    if math.isclose(low, high, rel_tol=1e-9, abs_tol=1e-12):
        padding = max(abs(low) * 0.05, 1.0)
        return low - padding, high + padding
    padding = (high - low) * 0.12
    return low - padding, high + padding


def center_signal(values: Sequence[float]) -> tuple[float, ...]:
    """Remove the window DC component for display and spectral analysis."""

    valid = _finite(values)
    baseline = sum(valid) / len(valid) if valid else 0.0
    return tuple(float(value) - baseline if math.isfinite(value) else math.nan for value in values)


def eeg_periodogram(
    values: Sequence[float],
    sample_rate: float,
    *,
    max_frequency: float = 45.0,
    max_samples: int = 512,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Compute a compact Hann-window periodogram without a numeric dependency."""

    if sample_rate <= 0 or len(values) < 8:
        return (), ()
    finite_values = _finite(values[-max_samples:])
    if len(finite_values) < 8:
        return (), ()
    mean = sum(finite_values) / len(finite_values)
    count = len(finite_values)
    windowed = [
        (value - mean) * (0.5 - 0.5 * math.cos(2.0 * math.pi * index / (count - 1)))
        for index, value in enumerate(finite_values)
    ]
    maximum_bin = min(count // 2, math.floor(max_frequency * count / sample_rate))
    frequencies: list[float] = []
    powers: list[float] = []
    scale = max(sum(value * value for value in windowed), 1e-12)
    for frequency_bin in range(1, maximum_bin + 1):
        angle_scale = -2.0 * math.pi * frequency_bin / count
        real = 0.0
        imaginary = 0.0
        for index, value in enumerate(windowed):
            angle = angle_scale * index
            real += value * math.cos(angle)
            imaginary += value * math.sin(angle)
        frequencies.append(frequency_bin * sample_rate / count)
        powers.append((real * real + imaginary * imaginary) / scale)
    return tuple(frequencies), tuple(powers)


def relative_band_powers(frequencies: Sequence[float], powers: Sequence[float]) -> tuple[float, ...]:
    band_values = [
        sum(power for frequency, power in zip(frequencies, powers, strict=False) if start <= frequency < stop)
        for _label, start, stop, _color in EEG_BANDS
    ]
    total = sum(band_values)
    if total <= 0:
        return tuple(0.0 for _ in band_values)
    return tuple(value * 100.0 / total for value in band_values)


def eeg_band_coverage(nyquist: float) -> tuple[str, ...]:
    """Describe whether each configured band is fully or partly observable."""

    return tuple(
        "full" if nyquist >= stop else "partial" if nyquist > start else "none"
        for _label, start, stop, _color in EEG_BANDS
    )


def stream_rate_text(window: DataWindow) -> str:
    """Prefer an observed rate once enough timestamped data is available."""

    nominal = window.descriptor.nominal_srate
    observed = window.observed_srate
    if observed is None or window.duration < 2.0 or len(window.timestamps) < 5:
        return f"{nominal:g} Hz" if nominal > 0 else "不规则采样"
    if nominal > 0 and abs(observed - nominal) > max(1.0, nominal * 0.1):
        return f"实测 {observed:.1f} Hz（元数据 {nominal:g} Hz）"
    return f"实测 {observed:.1f} Hz"


def effective_sample_rate(window: DataWindow) -> float:
    """Use a stable observed rate for analysis, falling back to LSL metadata."""

    if window.observed_srate is not None and window.duration >= 2.0 and len(window.timestamps) >= 5:
        return window.observed_srate
    return window.descriptor.nominal_srate


class SignalPanel(ttk.Frame):
    """Render each stream using a layout matched to its signal semantics."""

    def __init__(self, parent: Any, kind: str) -> None:
        super().__init__(parent, padding=(12, 10))
        self.kind = kind
        self.status = StringVar(value="等待 LSL 数据流")
        self._window: DataWindow | None = None
        self._seconds = 10.0
        self._scales: dict[str, tuple[float, float]] = {}
        self._analysis_sample_count = -1
        self._analysis_updated = 0.0
        self._eeg_spectra: tuple[tuple[tuple[float, ...], tuple[float, ...]], ...] = ()
        self._eeg_bands: tuple[float, ...] = ()
        self._eeg_frequency_limit = 45.0

        ttk.Label(self, textvariable=self.status).pack(anchor="w", pady=(0, 8))
        self.canvas = Canvas(
            self,
            background=PANEL_BACKGROUND,
            highlightthickness=1,
            highlightbackground="#DDE3EC",
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self._draw())

    def show_waiting(self, message: str = "等待 LSL 数据流") -> None:
        self._window = None
        self.status.set(message)
        self._draw()

    def render(self, window: DataWindow, seconds: float) -> None:
        self._window = window
        self._seconds = seconds
        descriptor = window.descriptor
        live_text = "● 实时" if window.is_live else "○ 等待新样本"
        display_note = {
            "eeg": "去直流显示 · 频谱每秒刷新",
            "fnirs": "735/850 nm 配对 · 去直流显示",
            "motion": "加速度/陀螺仪分组",
            "metric": "厂商未提供通道语义 · 稳健自适应纵轴",
            "general_metric": "厂商未提供 13 通道语义 · 仅按索引显示",
        }.get(self.kind, "稳健自适应纵轴")
        self.status.set(
            f"{live_text}  |  {descriptor.name}  |  {descriptor.channel_count} ch  |  "
            f"{stream_rate_text(window)}  |  累计 {window.total_samples_received:,} 样本  |  {display_note}"
        )
        if self.kind == "eeg":
            self._update_eeg_analysis(window)
        self._draw()

    def _draw(self) -> None:
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 480)
        height = max(self.canvas.winfo_height(), 360)
        data = self._window
        if data is None or not data.samples:
            self.canvas.create_text(
                width / 2,
                height / 2,
                text="尚未收到数据",
                fill=MUTED_COLOR,
                font=(UI_FONT_FAMILY, 15),
            )
            return
        if self.kind == "eeg":
            self._draw_eeg(data, width, height)
        elif self.kind == "fnirs":
            self._draw_fnirs(data, width, height)
        elif self.kind == "motion":
            self._draw_motion(data, width, height)
        else:
            self._draw_metrics(data, width, height)

    def _stable_limits(self, key: str, values: Iterable[float]) -> tuple[float, float]:
        target_low, target_high = robust_limits(values)
        previous = self._scales.get(key)
        if previous is None:
            result = target_low, target_high
        else:
            previous_low, previous_high = previous
            low = target_low if target_low < previous_low else previous_low + (target_low - previous_low) * 0.08
            high = target_high if target_high > previous_high else previous_high + (target_high - previous_high) * 0.08
            result = low, high
        self._scales[key] = result
        return result

    def _draw_time_grid(self, bounds: tuple[float, float, float, float], *, labels: bool = True) -> None:
        left, top, right, bottom = bounds
        for division in range(6):
            x = left + (right - left) * division / 5
            self.canvas.create_line(x, top, x, bottom, fill=GRID_COLOR)
            if labels:
                remaining = -self._seconds + self._seconds * division / 5
                self.canvas.create_text(
                    x,
                    bottom + 13,
                    text=f"{remaining:g}s",
                    fill=AXIS_COLOR,
                    font=(UI_FONT_FAMILY, 8),
                )

    def _draw_series(
        self,
        timestamps: Sequence[float],
        values: Sequence[float],
        bounds: tuple[float, float, float, float],
        limits: tuple[float, float],
        color: str,
        *,
        width: float = 1.5,
        max_points: int = 720,
    ) -> None:
        if len(timestamps) < 2 or len(values) < 2:
            return
        left, top, right, bottom = bounds
        low, high = limits
        scale = max(high - low, 1e-12)
        latest = timestamps[-1]
        earliest = latest - self._seconds
        count = min(len(timestamps), len(values))
        step = max(1, math.ceil(count / max_points))
        indexes = list(range(0, count, step))
        if indexes[-1] != count - 1:
            indexes.append(count - 1)
        points: list[float] = []
        for index in indexes:
            value = values[index]
            if not math.isfinite(value):
                continue
            x = left + (timestamps[index] - earliest) / self._seconds * (right - left)
            y = bottom - (value - low) / scale * (bottom - top)
            points.extend((x, max(top, min(bottom, y))))
        if len(points) >= 4:
            self.canvas.create_line(*points, fill=color, width=width, smooth=False)

    @staticmethod
    def _channel(data: DataWindow, index: int) -> tuple[float, ...]:
        return tuple(sample[index] if index < len(sample) else math.nan for sample in data.samples)

    def _draw_band_label(
        self,
        label: str,
        bounds: tuple[float, float, float, float],
        limits: tuple[float, float],
        color: str,
    ) -> None:
        left, top, right, _bottom = bounds
        low, high = limits
        self.canvas.create_oval(left - 70, top + 6, left - 62, top + 14, fill=color, outline="")
        self.canvas.create_text(
            left - 56,
            top + 10,
            text=label,
            anchor="w",
            fill=TEXT_COLOR,
            font=(UI_FONT_FAMILY, 9, "bold"),
        )
        self.canvas.create_text(
            right,
            top + 2,
            text=f"{low:.3g} … {high:.3g}",
            anchor="ne",
            fill=AXIS_COLOR,
            font=(UI_FONT_FAMILY, 8),
        )

    def _draw_eeg(self, data: DataWindow, width: int, height: int) -> None:
        left, right = 96.0, width - 22.0
        waveform_bottom = max(280.0, height * 0.56)
        channels = min(2, data.descriptor.channel_count)
        band_height = (waveform_bottom - 32.0) / max(channels, 1)
        for channel_index in range(channels):
            top = 20.0 + channel_index * band_height
            bottom = top + band_height - 10.0
            bounds = (left, top, right, bottom)
            self._draw_time_grid(bounds, labels=channel_index == channels - 1)
            centered = center_signal(self._channel(data, channel_index))
            limits = self._stable_limits(f"eeg-{channel_index}", centered)
            center_y = bottom - (0.0 - limits[0]) / max(limits[1] - limits[0], 1e-12) * (bottom - top)
            if top <= center_y <= bottom:
                self.canvas.create_line(left, center_y, right, center_y, fill="#DDE3EC")
            color = PLOT_COLORS[channel_index]
            self._draw_series(data.timestamps, centered, bounds, limits, color, width=1.7)
            self._draw_band_label(data.descriptor.channel_labels[channel_index], bounds, limits, color)

        analysis_top = waveform_bottom + 28.0
        if analysis_top >= height - 80:
            return
        middle = width * 0.52
        spectrum_bounds = (66.0, analysis_top + 28.0, middle - 26.0, height - 42.0)
        bands_bounds = (middle + 26.0, analysis_top + 28.0, width - 28.0, height - 42.0)
        self._draw_spectrum(spectrum_bounds)
        self._draw_band_powers(bands_bounds)

    def _update_eeg_analysis(self, data: DataWindow) -> None:
        now = time.monotonic()
        if self._eeg_spectra and now - self._analysis_updated < 1.0:
            return
        sample_rate = effective_sample_rate(data)
        self._eeg_frequency_limit = min(45.0, sample_rate / 2.0) if sample_rate > 0 else 45.0
        spectra = tuple(
            eeg_periodogram(self._channel(data, index), sample_rate)
            for index in range(min(2, data.descriptor.channel_count))
        )
        combined = [0.0] * (len(spectra[0][1]) if spectra else 0)
        frequencies = spectra[0][0] if spectra else ()
        for _spectrum_frequencies, powers in spectra:
            for index, power in enumerate(powers):
                if index < len(combined):
                    combined[index] += power / max(len(spectra), 1)
        self._eeg_spectra = spectra
        self._eeg_bands = relative_band_powers(frequencies, combined)
        self._analysis_sample_count = data.total_samples_received
        self._analysis_updated = now

    def _draw_spectrum(self, bounds: tuple[float, float, float, float]) -> None:
        left, top, right, bottom = bounds
        self.canvas.create_rectangle(left, top, right, bottom, outline="#DDE3EC")
        self.canvas.create_text(left, top - 16, text="EEG 频谱", anchor="w", fill=TEXT_COLOR, font=(UI_FONT_FAMILY, 11, "bold"))
        if not self._eeg_spectra:
            return
        frequency_limit = self._eeg_frequency_limit
        db_values = [10.0 * math.log10(max(power, 1e-12)) for _frequencies, powers in self._eeg_spectra for power in powers]
        low, high = robust_limits(db_values)
        for division in range(5):
            x = left + (right - left) * division / 4
            self.canvas.create_line(x, top, x, bottom, fill=GRID_COLOR)
            self.canvas.create_text(
                x,
                bottom + 12,
                text=f"{frequency_limit * division / 4:.1f}",
                fill=AXIS_COLOR,
                font=(UI_FONT_FAMILY, 8),
            )
        self.canvas.create_text((left + right) / 2, bottom + 27, text="频率 (Hz)", fill=AXIS_COLOR, font=(UI_FONT_FAMILY, 8))
        for channel_index, (frequencies, powers) in enumerate(self._eeg_spectra):
            points: list[float] = []
            for frequency, power in zip(frequencies, powers, strict=False):
                x = left + frequency / max(frequency_limit, 1e-12) * (right - left)
                db = 10.0 * math.log10(max(power, 1e-12))
                y = bottom - (db - low) / max(high - low, 1e-12) * (bottom - top)
                points.extend((x, max(top, min(bottom, y))))
            if len(points) >= 4:
                self.canvas.create_line(*points, fill=PLOT_COLORS[channel_index], width=1.5)
        self.canvas.create_text(left + 8, top + 8, text=f"{high:.0f} dB", anchor="nw", fill=AXIS_COLOR, font=(UI_FONT_FAMILY, 8))
        self.canvas.create_text(left + 8, bottom - 8, text=f"{low:.0f} dB", anchor="sw", fill=AXIS_COLOR, font=(UI_FONT_FAMILY, 8))

    def _draw_band_powers(self, bounds: tuple[float, float, float, float]) -> None:
        left, top, right, bottom = bounds
        self.canvas.create_rectangle(left, top, right, bottom, outline="#DDE3EC")
        title = "EEG 相对频带功率"
        if self._eeg_frequency_limit < 45.0:
            title += f"（Nyquist {self._eeg_frequency_limit:.1f} Hz）"
        self.canvas.create_text(
            left,
            top - 16,
            text=title,
            anchor="w",
            fill=TEXT_COLOR,
            font=(UI_FONT_FAMILY, 11, "bold"),
        )
        if not self._eeg_bands:
            return
        maximum = max(max(self._eeg_bands) * 1.15, 20.0)
        gap = 10.0
        bar_width = ((right - left) - gap * (len(EEG_BANDS) + 1)) / len(EEG_BANDS)
        coverage = eeg_band_coverage(self._eeg_frequency_limit)
        for index, ((label, start, stop, color), value, band_coverage) in enumerate(
            zip(EEG_BANDS, self._eeg_bands, coverage, strict=True)
        ):
            x0 = left + gap + index * (bar_width + gap)
            x1 = x0 + bar_width
            y = bottom - value / maximum * (bottom - top - 24.0)
            if band_coverage != "none":
                self.canvas.create_rectangle(x0, y, x1, bottom, fill=color, outline="")
            value_text = "N/A" if band_coverage == "none" else f"{value:.1f}%{'*' if band_coverage == 'partial' else ''}"
            self.canvas.create_text(
                (x0 + x1) / 2,
                (bottom - 9) if band_coverage == "none" else (y - 9),
                text=value_text,
                fill=TEXT_COLOR,
                font=(UI_FONT_FAMILY, 8, "bold"),
            )
            self.canvas.create_text((x0 + x1) / 2, bottom + 12, text=label, fill=TEXT_COLOR, font=(UI_FONT_FAMILY, 8))
            self.canvas.create_text((x0 + x1) / 2, bottom + 25, text=f"{start:g}–{stop:g}Hz", fill=AXIS_COLOR, font=(UI_FONT_FAMILY, 7))

    def _draw_fnirs(self, data: DataWindow, width: int, height: int) -> None:
        if data.descriptor.channel_count < 16:
            self._draw_stacked(data, width, height, center=True)
            return
        left, right, top, bottom = 102.0, width - 24.0, 30.0, height - 34.0
        pair_count = min(8, data.descriptor.channel_count // 2)
        band_height = (bottom - top) / pair_count
        self.canvas.create_rectangle(right - 185, 8, right - 174, 19, fill=WAVELENGTH_COLORS[0], outline="")
        self.canvas.create_text(right - 168, 14, text="735 nm", anchor="w", fill=TEXT_COLOR, font=(UI_FONT_FAMILY, 8))
        self.canvas.create_rectangle(right - 96, 8, right - 85, 19, fill=WAVELENGTH_COLORS[1], outline="")
        self.canvas.create_text(right - 79, 14, text="850 nm", anchor="w", fill=TEXT_COLOR, font=(UI_FONT_FAMILY, 8))
        for pair_index in range(pair_count):
            band_top = top + pair_index * band_height
            band_bottom = band_top + band_height - 6.0
            bounds = (left, band_top, right, band_bottom)
            self._draw_time_grid(bounds, labels=pair_index == pair_count - 1)
            first = center_signal(self._channel(data, pair_index))
            second = center_signal(self._channel(data, pair_index + pair_count))
            limits = self._stable_limits(f"fnirs-{pair_index}", (*first, *second))
            center_y = band_bottom - (0.0 - limits[0]) / max(limits[1] - limits[0], 1e-12) * (band_bottom - band_top)
            if band_top <= center_y <= band_bottom:
                self.canvas.create_line(left, center_y, right, center_y, fill="#DDE3EC")
            self._draw_series(data.timestamps, first, bounds, limits, WAVELENGTH_COLORS[0], width=1.45)
            self._draw_series(data.timestamps, second, bounds, limits, WAVELENGTH_COLORS[1], width=1.45)
            label = data.descriptor.channel_labels[pair_index].split(" · ", 1)[0]
            self.canvas.create_text(left - 12, (band_top + band_bottom) / 2, text=label, anchor="e", fill=TEXT_COLOR, font=(UI_FONT_FAMILY, 9, "bold"))
            self.canvas.create_text(right, band_top + 2, text=f"±{max(abs(limits[0]), abs(limits[1])):.3g}", anchor="ne", fill=AXIS_COLOR, font=(UI_FONT_FAMILY, 7))

    def _draw_motion(self, data: DataWindow, width: int, height: int) -> None:
        left, right = 94.0, width - 24.0
        gap = 34.0
        group_height = (height - 62.0 - gap) / 2
        groups = (("加速度", 0, "g"), ("陀螺仪", 3, "°/s"))
        for group_index, (title, start_index, unit) in enumerate(groups):
            top = 28.0 + group_index * (group_height + gap)
            bottom = top + group_height
            bounds = (left, top, right, bottom)
            self._draw_time_grid(bounds, labels=True)
            channel_values = [self._channel(data, index) for index in range(start_index, min(start_index + 3, data.descriptor.channel_count))]
            limits = self._stable_limits(f"motion-{group_index}", (value for values in channel_values for value in values))
            zero_y = bottom - (0.0 - limits[0]) / max(limits[1] - limits[0], 1e-12) * (bottom - top)
            if top <= zero_y <= bottom:
                self.canvas.create_line(left, zero_y, right, zero_y, fill="#CCD4DF")
            self.canvas.create_text(left, top - 16, text=f"{title} ({unit})", anchor="w", fill=TEXT_COLOR, font=(UI_FONT_FAMILY, 10, "bold"))
            for offset, values in enumerate(channel_values):
                color = MOTION_COLORS[offset]
                self._draw_series(data.timestamps, values, bounds, limits, color, width=1.7)
                label = data.descriptor.channel_labels[start_index + offset].split()[-1]
                legend_x = right - 150 + offset * 52
                self.canvas.create_line(legend_x, top - 15, legend_x + 14, top - 15, fill=color, width=3)
                self.canvas.create_text(legend_x + 19, top - 15, text=label, anchor="w", fill=TEXT_COLOR, font=(UI_FONT_FAMILY, 8))
            self.canvas.create_text(right, top + 4, text=f"{limits[1]:.3g}", anchor="ne", fill=AXIS_COLOR, font=(UI_FONT_FAMILY, 8))
            self.canvas.create_text(right, bottom - 4, text=f"{limits[0]:.3g}", anchor="se", fill=AXIS_COLOR, font=(UI_FONT_FAMILY, 8))

    def _draw_metrics(self, data: DataWindow, width: int, height: int) -> None:
        channel_count = data.descriptor.channel_count
        if channel_count <= 2:
            self._draw_metric_trends(data, width, height)
            return
        columns = 4 if width < 1200 else 5
        rows = math.ceil(channel_count / columns)
        gap = 12.0
        left, top = 20.0, 20.0
        card_width = (width - left * 2 - gap * (columns - 1)) / columns
        card_height = (height - top * 2 - gap * (rows - 1)) / rows
        latest = data.samples[-1]
        for index in range(channel_count):
            row, column = divmod(index, columns)
            x0 = left + column * (card_width + gap)
            y0 = top + row * (card_height + gap)
            x1, y1 = x0 + card_width, y0 + card_height
            self.canvas.create_rectangle(x0, y0, x1, y1, fill="#FBFCFE", outline="#DDE3EC")
            label = data.descriptor.channel_labels[index]
            value = latest[index] if index < len(latest) else math.nan
            self.canvas.create_text(x0 + 14, y0 + 14, text=label, anchor="nw", fill=MUTED_COLOR, font=(UI_FONT_FAMILY, 9))
            self.canvas.create_text(
                x0 + 14,
                y0 + 42,
                text=f"{value:.3g}" if math.isfinite(value) else "—",
                anchor="nw",
                fill=TEXT_COLOR,
                font=(UI_FONT_FAMILY, 19, "bold"),
            )
            values = self._channel(data, index)
            spark_bounds = (x0 + 12, y0 + card_height * 0.62, x1 - 12, y1 - 12)
            limits = robust_limits(values)
            self._draw_series(data.timestamps, values, spark_bounds, limits, PLOT_COLORS[index % len(PLOT_COLORS)], width=1.3, max_points=180)

    def _draw_metric_trends(self, data: DataWindow, width: int, height: int) -> None:
        channel_count = data.descriptor.channel_count
        latest = data.samples[-1]
        card_height = min(116.0, height * 0.22)
        gap = 14.0
        card_width = (width - 40.0 - gap * (channel_count - 1)) / channel_count
        for index in range(channel_count):
            x0 = 20.0 + index * (card_width + gap)
            x1 = x0 + card_width
            color = PLOT_COLORS[index]
            self.canvas.create_rectangle(x0, 18, x1, card_height, fill="#FBFCFE", outline="#DDE3EC")
            self.canvas.create_rectangle(x0, 18, x0 + 5, card_height, fill=color, outline="")
            label = data.descriptor.channel_labels[index]
            value = latest[index] if index < len(latest) else math.nan
            unit = " bpm" if self.kind == "heart_rate" else ""
            self.canvas.create_text(x0 + 18, 34, text=label, anchor="w", fill=MUTED_COLOR, font=(UI_FONT_FAMILY, 10))
            self.canvas.create_text(
                x0 + 18,
                72,
                text=f"{value:.3g}{unit}" if math.isfinite(value) else "—",
                anchor="w",
                fill=TEXT_COLOR,
                font=(UI_FONT_FAMILY, 24, "bold"),
            )
        plot_top = card_height + 30.0
        plot_bottom = height - 36.0
        band_height = (plot_bottom - plot_top) / max(channel_count, 1)
        for index in range(channel_count):
            top = plot_top + index * band_height
            bottom = top + band_height - 8.0
            bounds = (78.0, top, width - 24.0, bottom)
            self._draw_time_grid(bounds, labels=index == channel_count - 1)
            values = self._channel(data, index)
            limits = self._stable_limits(f"metric-{index}", values)
            color = PLOT_COLORS[index]
            self._draw_series(data.timestamps, values, bounds, limits, color, width=1.8)
            self._draw_band_label(data.descriptor.channel_labels[index], bounds, limits, color)

    def _draw_stacked(self, data: DataWindow, width: int, height: int, *, center: bool = False) -> None:
        channel_count = min(data.descriptor.channel_count, 8)
        left, right, top, bottom = 96.0, width - 24.0, 24.0, height - 34.0
        band_height = (bottom - top) / max(channel_count, 1)
        for index in range(channel_count):
            band_top = top + index * band_height
            band_bottom = band_top + band_height - 5.0
            bounds = (left, band_top, right, band_bottom)
            self._draw_time_grid(bounds, labels=index == channel_count - 1)
            values = self._channel(data, index)
            if center:
                values = center_signal(values)
            limits = self._stable_limits(f"stack-{index}", values)
            color = PLOT_COLORS[index % len(PLOT_COLORS)]
            self._draw_series(data.timestamps, values, bounds, limits, color)
            self._draw_band_label(data.descriptor.channel_labels[index], bounds, limits, color)


class LiveMonitorWindow:
    """Own a live stream manager and periodically render immutable snapshots."""

    def __init__(self, window: Tk | Toplevel, manager: LiveStreamManager | None = None) -> None:
        self.window = window
        self.manager = manager or LiveStreamManager()
        self.time_range = StringVar(value="10")
        self.paused = BooleanVar(value=False)
        self.overall_status = StringVar(value="正在扫描本机网络中的 LSL 数据流…")
        self._after_id: str | None = None
        self._closed = False

        self.window.title("BSense-R 实时数据监测")
        self.window.geometry("1400x900")
        self.window.minsize(1000, 680)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._build_view()
        self.manager.start()
        self._update()

    def _build_view(self) -> None:
        style = ttk.Style(self.window)
        style.configure("Monitor.TFrame", background=BACKGROUND)
        root = ttk.Frame(self.window, padding=18, style="Monitor.TFrame")
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="BSense-R 实时数据", font=(UI_FONT_FAMILY, 20, "bold")).pack(side="left")
        ttk.Button(header, text="重新扫描", command=self._refresh).pack(side="right")
        ttk.Checkbutton(header, text="暂停显示", variable=self.paused).pack(side="right", padx=12)
        ttk.Label(header, text="时间范围").pack(side="right", padx=(12, 6))
        ttk.Combobox(
            header,
            textvariable=self.time_range,
            values=("5", "10", "20"),
            width=5,
            state="readonly",
        ).pack(side="right")
        ttk.Label(header, text="秒").pack(side="right", padx=(4, 0))

        ttk.Label(root, textvariable=self.overall_status).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            root,
            text="实时显示使用时钟校正、去抖和单调时间戳；绘图处理不修改内置录制器写入的原始 LSL 数据。",
            foreground=MUTED_COLOR,
        ).pack(anchor="w", pady=(0, 12))

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)
        self.panels: dict[str, SignalPanel] = {}
        for kind in SUPPORTED_STREAM_KINDS:
            panel = SignalPanel(self.notebook, kind)
            self.notebook.add(panel, text=f"○ {STREAM_KIND_LABELS[kind]}")
            self.panels[kind] = panel

    def _refresh(self) -> None:
        self.overall_status.set("正在重新扫描 LSL 数据流…")
        self.manager.refresh()

    def _active_kind(self) -> str:
        try:
            index = self.notebook.index(self.notebook.select())
        except Exception:  # noqa: BLE001 - Tk can briefly have no selected tab while closing
            index = 0
        return SUPPORTED_STREAM_KINDS[min(index, len(SUPPORTED_STREAM_KINDS) - 1)]

    def _update(self) -> None:
        if self._closed:
            return
        seconds = float(self.time_range.get())
        errors = self.manager.errors()
        connected = 0
        live = 0
        stream_states: dict[str, DataWindow | None] = {}
        for index, kind in enumerate(SUPPORTED_STREAM_KINDS):
            data = self.manager.window(kind, seconds, max_points=2)
            stream_states[kind] = data
            connected += int(data is not None)
            is_live = data is not None and data.is_live
            live += int(is_live)
            state_symbol = "●" if is_live else "○"
            self.notebook.tab(index, text=f"{state_symbol} {STREAM_KIND_LABELS[kind]}")

        if not self.paused.get():
            active_kind = self._active_kind()
            panel = self.panels[active_kind]
            preview = stream_states[active_kind]
            error = errors.get(active_kind)
            if error:
                if preview is None or not preview.samples:
                    panel.show_waiting(f"LSL 接收失败：{error}")
                else:
                    data = self.manager.window(active_kind, seconds)
                    if data is not None:
                        panel.render(data, seconds)
                        panel.status.set(f"LSL 接收已中断：{error}  |  当前仅显示最后收到的数据")
            elif preview is None:
                panel.show_waiting("等待 BioMultiLite 发布此 LSL 流")
            else:
                data = self.manager.window(active_kind, seconds)
                if data is not None:
                    panel.render(data, seconds)

        discovery_error = errors.get("discovery")
        if discovery_error and not connected:
            self.overall_status.set(f"LSL 扫描失败：{discovery_error}")
        elif connected:
            paused_text = "（显示已暂停，接收缓冲继续）" if self.paused.get() else ""
            stream_errors = sum(kind in errors for kind in SUPPORTED_STREAM_KINDS)
            error_text = f"  |  {stream_errors} 类接收异常" if stream_errors else ""
            missing_source_id = any(not descriptor.source_id for descriptor in self.manager.descriptors())
            recovery_text = "  |  厂商流无 source_id，发布端重启后需重新扫描" if missing_source_id else ""
            self.overall_status.set(
                f"已发现 {connected}/6 类数据流，{live}/6 类正在接收样本  |  显示刷新 5 FPS {paused_text}"
                f"{error_text}{recovery_text}"
            )
        else:
            self.overall_status.set("未发现 BioMultiLite 数据流：请连接设备，并在 BioMultiLite 的 LSL 页面勾选数据后点击 Start")
        self._after_id = self.window.after(200, self._update)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._after_id is not None:
            self.window.after_cancel(self._after_id)
            self._after_id = None
        self.manager.stop()
        self.window.destroy()


def run_live_monitor() -> None:
    root = Tk()
    LiveMonitorWindow(root)
    root.mainloop()


def main() -> None:
    run_live_monitor()


if __name__ == "__main__":
    main()
