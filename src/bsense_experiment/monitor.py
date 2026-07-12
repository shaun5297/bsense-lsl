"""Tkinter live monitor for BioMultiLite LSL streams."""

from __future__ import annotations

import math
from tkinter import BooleanVar, Canvas, StringVar, Tk, Toplevel, ttk
from typing import Any

from .live import DataWindow, LiveStreamManager, STREAM_KIND_LABELS, SUPPORTED_STREAM_KINDS


PLOT_COLORS = ("#4C8BF5", "#34A853", "#F9AB00", "#EA4335", "#7E57C2", "#00ACC1", "#EC407A", "#8D6E63")


class WaveformPanel(ttk.Frame):
    """A lightweight multi-channel time-series view without extra dependencies."""

    def __init__(self, parent: Any, max_visible_channels: int = 8) -> None:
        super().__init__(parent, padding=(12, 10))
        self.max_visible_channels = max_visible_channels
        self.status = StringVar(value="等待 LSL 数据流")
        self._window: DataWindow | None = None

        ttk.Label(self, textvariable=self.status).pack(anchor="w", pady=(0, 8))
        self.canvas = Canvas(self, background="#FFFFFF", highlightthickness=1, highlightbackground="#DADCE0")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self._draw())

    def show_waiting(self, message: str = "等待 LSL 数据流") -> None:
        self._window = None
        self.status.set(message)
        self._draw()

    def render(self, window: DataWindow) -> None:
        self._window = window
        descriptor = window.descriptor
        live_text = "实时" if window.is_live else "等待新样本"
        visible = min(descriptor.channel_count, self.max_visible_channels)
        channel_note = f"，显示前 {visible}/{descriptor.channel_count} 通道" if visible < descriptor.channel_count else ""
        self.status.set(
            f"{live_text}  |  {descriptor.name}  |  {descriptor.channel_count} ch  |  "
            f"{descriptor.nominal_srate:g} Hz  |  累计 {window.total_samples_received:,} 样本{channel_note}"
        )
        self._draw()

    def _draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 240)
        data = self._window
        if data is None or not data.samples:
            canvas.create_text(width / 2, height / 2, text="尚未收到数据", fill="#80868B", font=("Microsoft YaHei UI", 14))
            return

        descriptor = data.descriptor
        channel_count = min(descriptor.channel_count, self.max_visible_channels)
        left, right, top, bottom = 88.0, 18.0, 24.0, 30.0
        plot_width = max(width - left - right, 1.0)
        plot_height = max(height - top - bottom, 1.0)
        band_height = plot_height / channel_count
        start_time = data.timestamps[0]
        duration = max(data.timestamps[-1] - start_time, 1e-6)

        for division in range(6):
            x = left + plot_width * division / 5
            canvas.create_line(x, top, x, top + plot_height, fill="#F1F3F4")
            elapsed = duration * division / 5
            canvas.create_text(x, height - 13, text=f"{elapsed:.1f}s", fill="#80868B", font=("Segoe UI", 8))

        for channel_index in range(channel_count):
            band_top = top + channel_index * band_height
            band_bottom = band_top + band_height
            center = (band_top + band_bottom) / 2
            canvas.create_line(left, center, width - right, center, fill="#E8EAED")
            if channel_index:
                canvas.create_line(left, band_top, width - right, band_top, fill="#F1F3F4")

            finite_values = [
                sample[channel_index]
                for sample in data.samples
                if channel_index < len(sample) and math.isfinite(sample[channel_index])
            ]
            label = descriptor.channel_labels[channel_index]
            canvas.create_text(left - 8, center, text=label, anchor="e", fill="#3C4043", font=("Segoe UI", 9, "bold"))
            if not finite_values:
                continue
            low, high = min(finite_values), max(finite_values)
            if math.isclose(low, high):
                padding = max(abs(low) * 0.05, 1.0)
                low -= padding
                high += padding
            else:
                padding = (high - low) * 0.05
                low -= padding
                high += padding
            scale = max(high - low, 1e-12)
            y_top = band_top + 5
            y_height = max(band_height - 10, 1.0)
            points: list[float] = []
            for timestamp, sample in zip(data.timestamps, data.samples, strict=False):
                value = sample[channel_index]
                if not math.isfinite(value):
                    continue
                x = left + (timestamp - start_time) / duration * plot_width
                y = y_top + (high - value) / scale * y_height
                points.extend((x, y))
            if len(points) >= 4:
                canvas.create_line(*points, fill=PLOT_COLORS[channel_index % len(PLOT_COLORS)], width=1.3)
            canvas.create_text(
                width - right,
                band_top + 2,
                text=f"{low:.3g} .. {high:.3g}",
                anchor="ne",
                fill="#9AA0A6",
                font=("Segoe UI", 7),
            )


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
        self.window.geometry("1280x820")
        self.window.minsize(900, 600)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._build_view()
        self.manager.start()
        self._update()

    def _build_view(self) -> None:
        root = ttk.Frame(self.window, padding=18)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="BSense-R 实时数据", font=("Microsoft YaHei UI", 20, "bold")).pack(side="left")
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

        ttk.Label(root, textvariable=self.overall_status).pack(anchor="w", pady=(0, 10))
        ttk.Label(
            root,
            text="本窗口只订阅 LSL；LabRecorder 可同时录制同一数据流。显示数据不写入磁盘。",
            foreground="#5F6368",
        ).pack(anchor="w", pady=(0, 12))

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        self.panels: dict[str, WaveformPanel] = {}
        for kind in SUPPORTED_STREAM_KINDS:
            panel = WaveformPanel(notebook)
            notebook.add(panel, text=STREAM_KIND_LABELS[kind])
            self.panels[kind] = panel

    def _refresh(self) -> None:
        self.overall_status.set("正在重新扫描 LSL 数据流…")
        self.manager.refresh()

    def _update(self) -> None:
        if self._closed:
            return
        seconds = float(self.time_range.get())
        connected = 0
        live = 0
        errors = self.manager.errors()
        if not self.paused.get():
            for kind, panel in self.panels.items():
                data = self.manager.window(kind, seconds, max_points=900)
                error = errors.get(kind)
                if error and (data is None or not data.samples):
                    panel.show_waiting(f"LSL 接收失败：{error}")
                    connected += int(data is not None)
                    continue
                if data is None:
                    panel.show_waiting("等待 BioMultiLite 发布此 LSL 流")
                    continue
                connected += 1
                live += int(data.is_live)
                panel.render(data)
        else:
            connected = len(self.manager.descriptors())
            live = sum(
                1
                for kind in SUPPORTED_STREAM_KINDS
                if (data := self.manager.window(kind, seconds, max_points=2)) is not None and data.is_live
            )
        discovery_error = errors.get("discovery")
        if discovery_error and not connected:
            self.overall_status.set(f"LSL 扫描失败：{discovery_error}")
        elif connected:
            paused_text = "（显示已暂停，采集缓冲继续）" if self.paused.get() else ""
            self.overall_status.set(f"已发现 {connected} 类数据流，{live} 类正在接收样本 {paused_text}")
        else:
            self.overall_status.set("未发现 BioMultiLite 数据流：请连接设备，并在 BioMultiLite 的 LSL 页面勾选数据后点击 Start")
        self._after_id = self.window.after(100, self._update)

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
