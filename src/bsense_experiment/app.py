#!/usr/bin/env python3
"""Run BSense-R experiment cues and record precise LSL markers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import socket
import sys
import threading
import time
from pathlib import Path
from queue import Empty, SimpleQueue
from tkinter import BooleanVar, Frame, Label, PhotoImage, StringVar, Tk, Toplevel, messagebox, ttk
from typing import TYPE_CHECKING, Callable

from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, cf_string, local_clock

from . import __version__
from .embedded_recorder import EmbeddedRecorderClient
from .participant import (
    HAND_OPTIONS,
    SEX_OPTIONS,
    save_participant_profile,
    validate_participant_profile,
)
from .platform_support import (
    VOICE_CUE_TEXTS,
    VOICE_CUE_VOICE,
    audio_cues_supported,
    default_output_root,
    launch_labrecorder,
    play_audio_cue,
    ui_font_family,
)
from .live import DataWindow, LiveStreamManager, STREAM_KIND_LABELS, SUPPORTED_STREAM_KINDS, describe_stream
from .protocols import (
    PROTOCOLS,
    PROTOCOL_BY_TASK,
    InputField,
    Step,
    build_deviceqc_plan,
    build_protocol_plan,
    estimate_protocol_seconds,
)
from .readiness import assess_readiness, classify_sart_trial
from .resources import object_asset_path

if TYPE_CHECKING:
    from .monitor import LiveMonitorWindow

APP_VERSION = __version__
MARKER_STREAM_NAME = "BSense Experiment Markers"
MARKER_STREAM_TYPE = "Markers"
DEFAULT_RCS_HOST = "127.0.0.1"
DEFAULT_RCS_PORT = 22345
LABRECORDER_STOP_TIMEOUT = 60.0
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
UI_FONT_FAMILY = ui_font_family()
RECORDING_MODE_EMBEDDED = "内置 XDF 录制（推荐）"
RECORDING_MODE_RCS = "LabRecorder RCS（兼容）"
RECORDING_MODE_MANUAL = "LabRecorder 手动（兼容）"
RECORDING_MODES = (RECORDING_MODE_EMBEDDED, RECORDING_MODE_RCS, RECORDING_MODE_MANUAL)
OBJECT_ASSETS = {
    "水杯": "cup.png",
    "手机": "mobilephone.png",
    "药瓶": "medicinebottle.png",
}
CUSTOM_ACQUISITION_BATCH = "自定义"
TWO_BATCH_A_LABEL = "两批方案 A｜探索性运动与意图"
TWO_BATCH_B_LABEL = "两批方案 B｜核心认知与疲劳"
THREE_BATCH_1_LABEL = "三批方案 1｜运动与意图"
THREE_BATCH_2_LABEL = "三批方案 2｜认知与注意"
THREE_BATCH_3_LABEL = "三批方案 3｜安全动作与疲劳"
QUICK_READINESS_LABEL = "赛道7｜脑状态安检"
ACQUISITION_BATCH_PRESETS: dict[str, tuple[str, tuple[str, ...], str]] = {
    QUICK_READINESS_LABEL: (
        "readiness_screen",
        ("m6_readiness",),
        "M6 上岗前快速筛查；自动计时约 4.7 分钟，另加状态确认。",
    ),
    TWO_BATCH_A_LABEL: (
        "two_part_a",
        ("m0_baseline", "m1_mi", "m4a_intent", "m4b_target"),
        "M0 → M1 → M4A → M4B；自动计时约 48.7 分钟。",
    ),
    TWO_BATCH_B_LABEL: (
        "two_part_b",
        ("m0_baseline", "m2_nback", "m3a_safety", "m3b_fatigue", "m5_debrief"),
        "M0 → M2 → M3A → M3B → M5；自动计时约 51.7 分钟，另加 M5 问卷。",
    ),
    THREE_BATCH_1_LABEL: (
        "three_part_1",
        ("m0_baseline", "m1_mi", "m4a_intent"),
        "M0 → M1 → M4A；自动计时约 39.9 分钟。",
    ),
    THREE_BATCH_2_LABEL: (
        "three_part_2",
        ("m0_baseline", "m2_nback", "m4b_target"),
        "M0 → M2 → M4B；自动计时约 44.8 分钟。",
    ),
    THREE_BATCH_3_LABEL: (
        "three_part_3",
        ("m0_baseline", "m3a_safety", "m3b_fatigue", "m5_debrief"),
        "M0 → M3A → M3B → M5；自动计时约 21.3 分钟，另加 M5 问卷。",
    ),
}
TASK_SIGNAL_KINDS = ("eeg", "fnirs", "motion")
TASK_BG = "#141a22"
TASK_FG = "#f5f7fa"
TASK_MUTED_FG = "#9aa7b8"
TASK_ACCENT = "#4da3ff"
BSENSE_EEG_RAIL_ABS = 375_000.0
BSENSE_EEG_RAIL_TOLERANCE = 1_000.0
MI_ACCEL_SPAN_WARNING = 0.08
MI_GYRO_SPAN_WARNING = 5.0


def flat_channel_count(window: DataWindow) -> int:
    """Count channels that are finite but exactly constant in the visible window."""

    if len(window.samples) < 5:
        return 0
    flat_count = 0
    for channel_index in range(window.descriptor.channel_count):
        values = [
            row[channel_index]
            for row in window.samples
            if channel_index < len(row) and math.isfinite(row[channel_index])
        ]
        if len(values) >= 5 and max(values) - min(values) <= 1e-12:
            flat_count += 1
    return flat_count


def eeg_clipped_channel_count(window: DataWindow) -> int:
    """Count EEG channels stuck near the BSense rail or on an extreme plateau."""

    if len(window.samples) < 20:
        return 0
    clipped = 0
    for channel_index in range(window.descriptor.channel_count):
        values = [
            row[channel_index]
            for row in window.samples
            if channel_index < len(row) and math.isfinite(row[channel_index])
        ]
        if len(values) < 20 or max(values) - min(values) <= 1e-12:
            continue
        near_rail = sum(
            abs(abs(value) - BSENSE_EEG_RAIL_ABS) <= BSENSE_EEG_RAIL_TOLERANCE for value in values
        )
        extrema_plateau = max(values.count(min(values)), values.count(max(values)))
        if near_rail / len(values) >= 0.05 or extrema_plateau / len(values) >= 0.20:
            clipped += 1
    return clipped


def motion_activity_metrics(window: DataWindow) -> tuple[bool, float, float]:
    """Return a conservative MI movement warning and acceleration/gyro spans."""

    if window.descriptor.channel_count < 6 or len(window.samples) < 8:
        return False, 0.0, 0.0
    spans: list[float] = []
    for channel_index in range(6):
        values = [
            row[channel_index]
            for row in window.samples
            if channel_index < len(row) and math.isfinite(row[channel_index])
        ]
        spans.append(max(values) - min(values) if len(values) >= 8 else 0.0)
    accel_span = max(spans[:3])
    gyro_span = max(spans[3:6])
    warning = accel_span >= MI_ACCEL_SPAN_WARNING or gyro_span >= MI_GYRO_SPAN_WARNING
    return warning, accel_span, gyro_span


def validate_identifier(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned or not SAFE_ID_PATTERN.fullmatch(cleaned):
        raise ValueError(f"{field_name} 只能包含英文字母、数字、下划线和连字符")
    return cleaned


def build_xdf_filename(participant: str, session: str, task: str, run: str) -> str:
    return f"sub-{participant}_ses-{session}_task-{task}_run-{run}.xdf".lower()


class LabRecorderClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.diagnostics: list[dict] = []

    def _record_diagnostic(self, event: str, **values: object) -> None:
        self.diagnostics.append({"unix_time": time.time(), "event": event, **values})

    def connect(self) -> None:
        if self.sock is not None:
            return
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self._record_diagnostic("rcs_connected", host=self.host, port=self.port)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def command(self, command: str, response_timeout: float | None = None) -> str:
        self.connect()
        assert self.sock is not None
        previous_timeout = self.sock.gettimeout()
        if response_timeout is not None:
            self.sock.settimeout(response_timeout)
        try:
            self.sock.sendall((command + "\n").encode("utf-8"))
            response = b""
            while len(response) < 2:
                chunk = self.sock.recv(2 - len(response))
                if not chunk:
                    raise ConnectionError(f"LabRecorder 在响应命令 {command!r} 前断开连接")
                response += chunk
        except socket.timeout as error:
            timeout = response_timeout if response_timeout is not None else self.timeout
            self._record_diagnostic("rcs_timeout", command=command, timeout_seconds=timeout)
            raise TimeoutError(f"等待 LabRecorder 响应 {command!r} 超时（{timeout:.0f} 秒）") from error
        finally:
            if response_timeout is not None:
                self.sock.settimeout(previous_timeout)
        decoded = response.decode("ascii", errors="replace")
        self._record_diagnostic("rcs_command", command=command, response=decoded)
        if decoded != "OK":
            raise RuntimeError(f"LabRecorder 未确认命令 {command!r}，返回 {decoded!r}")
        return decoded

    @staticmethod
    def wait_for_xdf(path: Path, timeout: float = 12.0) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                size = 0
            if size > 0:
                return size
            time.sleep(0.25)
        raise RuntimeError(
            f"LabRecorder 返回了 OK，但 {path} 在 {timeout:.0f} 秒内没有创建。"
            "请查看 LabRecorder 窗口或控制台中的文件名、权限和录制错误。"
        )

    def start_recording(self, output_root: Path, filename: str) -> tuple[Path, int]:
        root_text = str(output_root.resolve())
        if any(character in root_text for character in "{}\r\n"):
            raise ValueError("数据目录不能包含大括号或换行")
        if any(character in filename for character in "{}\r\n"):
            raise ValueError("文件名不能包含大括号或换行")

        target_path = output_root.resolve() / filename
        if target_path.exists():
            raise FileExistsError(f"目标 XDF 已存在：{target_path}。请更换 Run 编号，避免覆盖或重命名混乱。")

        try:
            self.command("update")
            time.sleep(2.5)
            self.command("select all")
            self.command(f"filename {{root:{root_text}}} {{template:{filename}}}")
            time.sleep(0.5)
            self.command("start")
            initial_size = self.wait_for_xdf(target_path)
            self._record_diagnostic("xdf_created", path=str(target_path), size_bytes=initial_size)
            return target_path, initial_size
        except Exception:
            try:
                self.command("stop")
            except Exception as stop_error:  # noqa: BLE001 - included in diagnostics
                self._record_diagnostic("rcs_cleanup_failed", error=str(stop_error))
            self.close()
            raise

    def stop_recording(self, target_path: Path | None = None) -> int | None:
        try:
            self.command("stop", response_timeout=LABRECORDER_STOP_TIMEOUT)
        finally:
            self.close()
        if target_path is None:
            return None
        final_size = self.wait_for_xdf(target_path, timeout=5.0)
        self._record_diagnostic("xdf_closed", path=str(target_path), size_bytes=final_size)
        return final_size

    def write_diagnostics(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for record in self.diagnostics:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


class BSenseExperimentApp:
    def __init__(self, root: Tk, default_short: bool = False) -> None:
        self.root = root
        self.root.title("BSense-R 实验控制")
        self.root.geometry("1040x800")
        self.root.minsize(900, 800)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Escape>", lambda _event: self.abort_experiment())
        self.root.bind("<KeyPress-space>", self._on_response_key)

        self.participant = StringVar(value="pilot01")
        self.participant_name = StringVar(value="")
        self.participant_age = StringVar(value="")
        self.participant_sex = StringVar(value="")
        self.education_years = StringVar(value="")
        self.dominant_hand = StringVar(value="右")
        self.session = StringVar(value="01")
        self.run = StringVar(value="001")
        self.output_root = StringVar(value=str(default_output_root()))
        self.rcs_host = StringVar(value=DEFAULT_RCS_HOST)
        self.rcs_port = StringVar(value=str(DEFAULT_RCS_PORT))
        self.short_protocol = BooleanVar(value=default_short)
        self.older_adult = BooleanVar(value=False)
        self.recording_mode = StringVar(value=RECORDING_MODE_EMBEDDED)
        self.audio_enabled = BooleanVar(value=True)
        self.nback_feedback = BooleanVar(value=False)
        self.target_object = StringVar(value="水杯")
        self.nback_order = StringVar(value="由易到难（原方案）")
        self.acquisition_batch = StringVar(value=CUSTOM_ACQUISITION_BATCH)
        self.skip_m0 = BooleanVar(value=False)
        self.acquisition_batch_detail = StringVar(
            value="自由选择模块；正式任务建议包含 M0，跨日采集请更换 Session。"
        )
        self.consent_confirmed = BooleanVar(value=False)
        self.operator_ready = BooleanVar(value=False)
        self.streams_ready = BooleanVar(value=False)
        self.recorder_ready = BooleanVar(value=False)
        self.practice_ready = BooleanVar(value=False)
        self.status = StringVar(value="LSL Marker 流已发布，等待开始")
        self.estimate_text = StringVar(value="")
        self.selection_warning = StringVar(value="")
        self.setup_error = StringVar(value="")
        self.stream_check_status = StringVar(value="尚未自动扫描 LSL 数据流")
        self.task_signal_status = StringVar(value="信号状态：正在扫描 EEG、fNIRS、Motion……")
        self.module_vars = {
            protocol.task: BooleanVar(value=(protocol.task == ("deviceqc" if default_short else "m0_baseline")))
            for protocol in PROTOCOLS
        }
        for variable in (
            self.participant,
            self.participant_name,
            self.participant_age,
            self.participant_sex,
            self.education_years,
            self.dominant_hand,
            self.session,
        ):
            variable.trace_add("write", self._participant_form_changed)
        for variable in (self.output_root, self.rcs_host, self.rcs_port, self.recording_mode):
            variable.trace_add("write", self._recorder_config_changed)

        self.marker_outlet = self._create_marker_outlet()
        self.active = False
        self.stopping = False
        self.plan: list[Step] = []
        self.step_index = -1
        self.step_started = 0.0
        self.tick_id: str | None = None
        self.pending_advance_id: str | None = None
        self.step_generation = 0
        self.step_completion_started = False
        self.log_handle = None
        self.event_log_path: Path | None = None
        self.current_context: dict[str, object] = {}
        self.base_context: dict[str, str] = {}
        self.active_acquisition_batch_id = "custom"
        self.validated_rcs_port: int | None = None
        self.output_directory = Path()
        self.module_queue: list[str] = []
        self.module_index = -1
        self.current_task = ""
        self.current_response_time: float | None = None
        self.step_text_replaced = False
        self.block_results: dict[str, list[bool]] = {}
        self.readiness_trials: list[dict[str, object]] = []
        self.readiness_result: dict[str, object] | None = None
        self.readiness_quality_samples = 0
        self.readiness_quality_bad_samples = 0
        self.readiness_quality_issues: set[str] = set()
        self.form_variables: dict[str, StringVar] = {}
        self.form_error = StringVar(value="")
        self.object_images: dict[str, PhotoImage] = {}
        self.audio_warning_played = False
        self.motion_warning_generation: int | None = None
        self.pending_next_task: str | None = None
        self.recorder_started = False
        self.xdf_path: Path | None = None
        self.xdf_initial_size = 0
        self.xdf_current_size = 0
        self.last_file_poll = 0.0
        self.recorder_log_path: Path | None = None
        self.live_monitor: LiveMonitorWindow | None = None
        self.ui_actions: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self.ui_action_poll_id: str | None = None
        self.task_signal_manager = LiveStreamManager(buffer_seconds=10.0)
        self.task_signal_poll_id: str | None = None

        self._build_setup_view()
        self._build_task_view()
        self.task_frame.pack_forget()
        self.task_signal_manager.start()
        self.task_signal_poll_id = self.root.after(500, self._update_task_signal_status)
        self.ui_action_poll_id = self.root.after(50, self._poll_ui_actions)

    def _post_to_ui(self, action: Callable[[], None]) -> None:
        """Queue a Tk mutation for the main thread without calling Tk from workers."""

        self.ui_actions.put(action)

    def _poll_ui_actions(self) -> None:
        self.ui_action_poll_id = None
        try:
            while True:
                self.ui_actions.get_nowait()()
        except Empty:
            pass
        finally:
            if self.root.winfo_exists():
                self.ui_action_poll_id = self.root.after(50, self._poll_ui_actions)

    def _participant_form_changed(self, *_args: object) -> None:
        self.consent_confirmed.set(False)

    def _recorder_config_changed(self, *_args: object) -> None:
        self.recorder_ready.set(False)
        if hasattr(self, "recorder_ready_checkbutton"):
            self._update_recording_mode_controls()

    def _update_recording_mode_controls(self) -> None:
        mode = self.recording_mode.get()
        if mode == RECORDING_MODE_EMBEDDED:
            self.recorder_ready.set(True)
            self.recorder_ready_text.set("内置 XDF 录制已启用（无需 LabRecorder）")
            self.recorder_ready_checkbutton.configure(state="disabled")
        else:
            self.recorder_ready_text.set(
                "LabRecorder 已打开并启用 RCS" if mode == RECORDING_MODE_RCS else "LabRecorder 已打开并准备手动录制"
            )
            self.recorder_ready_checkbutton.configure(state="normal")
        rcs_state = "normal" if mode == RECORDING_MODE_RCS else "disabled"
        for entry in self.rcs_entries:
            entry.configure(state=rcs_state)

    @staticmethod
    def _create_marker_outlet() -> StreamOutlet:
        info = StreamInfo(
            MARKER_STREAM_NAME,
            MARKER_STREAM_TYPE,
            1,
            IRREGULAR_RATE,
            cf_string,
            "bsense-experiment-markers-v1",
        )
        desc = info.desc()
        desc.append_child_value("app_version", APP_VERSION)
        desc.append_child_value("payload_format", "json")
        desc.append_child_value("time_reference", "lsl_local_clock")
        channel = desc.append_child("channels").append_child("channel")
        channel.append_child_value("label", "Event")
        channel.append_child_value("type", "Marker")
        return StreamOutlet(info)

    def _build_setup_view(self) -> None:
        self.setup_frame = ttk.Frame(self.root, padding=22)
        self.setup_frame.pack(fill="both", expand=True)

        ttk.Label(self.setup_frame, text="BSense-R 模块化数据采集", font=(UI_FONT_FAMILY, 22, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            self.setup_frame,
            text="模块可独立运行或按顺序衔接；每个模块保存为独立 XDF，并在进入下一模块前确认。",
            font=(UI_FONT_FAMILY, 11),
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 12))

        self.setup_notebook = ttk.Notebook(self.setup_frame)
        self.setup_notebook.grid(row=2, column=0, columnspan=4, sticky="nsew")
        subject_tab = ttk.Frame(self.setup_notebook, padding=16)
        module_tab = ttk.Frame(self.setup_notebook, padding=16)
        recorder_tab = ttk.Frame(self.setup_notebook, padding=16)
        self.setup_notebook.add(subject_tab, text="1. 被试与会话")
        self.setup_notebook.add(module_tab, text="2. 实验模块")
        self.setup_notebook.add(recorder_tab, text="3. 录制检查")

        subject_fields = (
            ("匿名被试编号 *", self.participant),
            ("真实姓名（可选）", self.participant_name),
            ("年龄 *", self.participant_age),
            ("性别 *", self.participant_sex),
            ("受教育年限", self.education_years),
            ("惯用手 *", self.dominant_hand),
            ("会话编号 *", self.session),
            ("Run 编号 *", self.run),
        )
        for index, (label, variable) in enumerate(subject_fields):
            row = index // 2
            column = (index % 2) * 2
            ttk.Label(subject_tab, text=label).grid(row=row, column=column, sticky="w", pady=7)
            if variable is self.participant_sex:
                field = ttk.Combobox(subject_tab, textvariable=variable, values=SEX_OPTIONS, state="readonly")
            elif variable is self.dominant_hand:
                field = ttk.Combobox(subject_tab, textvariable=variable, values=HAND_OPTIONS, state="readonly")
            else:
                field = ttk.Entry(subject_tab, textvariable=variable)
            field.grid(row=row, column=column + 1, sticky="ew", padx=(10, 24 if column == 0 else 0), pady=7)
        ttk.Checkbutton(
            subject_tab,
            text="已获得被试知情同意，并确认资料录入准确 *",
            variable=self.consent_confirmed,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(14, 6))
        ttk.Label(
            subject_tab,
            text="姓名只写入 participants 下的本地资料，不进入 XDF、文件名或逐条 Marker。",
            foreground="#7a4b00",
        ).grid(row=5, column=0, columnspan=4, sticky="w")
        subject_tab.columnconfigure(1, weight=1)
        subject_tab.columnconfigure(3, weight=1)

        module_frame = ttk.LabelFrame(module_tab, text="实验模块（可多选，按下列顺序执行）", padding=12)
        module_frame.grid(row=0, column=0, columnspan=4, sticky="nsew", pady=(0, 12))
        ttk.Label(module_frame, text="采集批次预设").grid(row=0, column=0, sticky="w", pady=(0, 6))
        batch_combobox = ttk.Combobox(
            module_frame,
            textvariable=self.acquisition_batch,
            values=(CUSTOM_ACQUISITION_BATCH, *ACQUISITION_BATCH_PRESETS),
            state="readonly",
            width=34,
        )
        batch_combobox.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 6))
        batch_combobox.bind("<<ComboboxSelected>>", self._apply_acquisition_batch)
        ttk.Label(
            module_frame,
            textvariable=self.acquisition_batch_detail,
            foreground="#315f8c",
            wraplength=760,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Checkbutton(
            module_frame,
            text="本日同会话已完成 M0，跳过基线模块（跨日或重新佩戴后不得跳过）",
            variable=self.skip_m0,
            command=self._skip_m0_changed,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        for index, protocol in enumerate(PROTOCOLS):
            checkbutton = ttk.Checkbutton(
                module_frame,
                text=f"{protocol.title} [{protocol.priority}]  {protocol.description}",
                variable=self.module_vars[protocol.task],
                command=self._module_selection_changed,
            )
            checkbutton.grid(row=index + 3, column=0, columnspan=2, sticky="w", padx=(0, 18), pady=4)
        module_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            module_tab,
            text="短流程（仅用于流程联调，不作为正式训练数据）",
            variable=self.short_protocol,
            command=self._update_estimate,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(
            module_tab,
            text="老年被试节奏（M1 想象 5 秒、休息 4 秒、组间休息 5 分钟）",
            variable=self.older_adult,
            command=self._update_estimate,
        ).grid(row=1, column=2, columnspan=2, sticky="w", pady=6)
        ttk.Label(module_tab, text="M4B 目标物体").grid(row=2, column=0, sticky="w", pady=6)
        target_combobox = ttk.Combobox(
            module_tab,
            textvariable=self.target_object,
            values=("水杯", "药瓶", "手机"),
            state="readonly",
            width=12,
        )
        target_combobox.grid(row=2, column=1, sticky="w", pady=6)
        target_combobox.bind("<<ComboboxSelected>>", self._practice_config_changed)
        ttk.Label(module_tab, text="正式研究应在被试之间平衡三种目标", foreground="#7a4b00").grid(
            row=2,
            column=2,
            columnspan=2,
            sticky="w",
            pady=6,
        )
        ttk.Label(module_tab, text="M2 负荷顺序").grid(row=3, column=0, sticky="w", pady=6)
        nback_combobox = ttk.Combobox(
            module_tab,
            textvariable=self.nback_order,
            values=("由易到难（原方案）", "拉丁方平衡（需先练习）"),
            state="readonly",
            width=24,
        )
        nback_combobox.grid(row=3, column=1, sticky="w", pady=6)
        nback_combobox.bind("<<ComboboxSelected>>", self._practice_config_changed)
        ttk.Checkbutton(
            module_tab,
            text="按键正误颜色（仅练习；正式关闭）",
            variable=self.nback_feedback,
            command=self._practice_config_changed,
        ).grid(
            row=3,
            column=2,
            columnspan=2,
            sticky="w",
            pady=6,
        )
        module_tab.columnconfigure(0, weight=1)
        module_tab.columnconfigure(1, weight=1)
        module_tab.columnconfigure(2, weight=1)
        module_tab.columnconfigure(3, weight=1)

        ttk.Label(recorder_tab, text="录制方式").grid(row=0, column=0, sticky="w", pady=7)
        ttk.Combobox(
            recorder_tab,
            textvariable=self.recording_mode,
            values=RECORDING_MODES,
            state="readonly",
        ).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(10, 0), pady=7)
        recorder_fields = (("数据目录", self.output_root), ("RCS 主机", self.rcs_host), ("RCS 端口", self.rcs_port))
        self.rcs_entries: list[ttk.Entry] = []
        for row, (label, variable) in enumerate(recorder_fields, start=1):
            ttk.Label(recorder_tab, text=label).grid(row=row, column=0, sticky="w", pady=7)
            entry = ttk.Entry(recorder_tab, textvariable=variable)
            entry.grid(
                row=row,
                column=1,
                columnspan=3,
                sticky="ew",
                padx=(10, 0),
                pady=7,
            )
            if variable in (self.rcs_host, self.rcs_port):
                self.rcs_entries.append(entry)
        ttk.Checkbutton(
            recorder_tab,
            text="启用中文女声过渡提示",
            variable=self.audio_enabled,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(12, 5))
        ttk.Checkbutton(recorder_tab, text="操作员在场且被试坐姿安全", variable=self.operator_ready).grid(
            row=5, column=0, columnspan=4, sticky="w", pady=4
        )
        ttk.Checkbutton(recorder_tab, text="BioMultiLite 已连接且 7 类 LSL 流已启动", variable=self.streams_ready).grid(
            row=6, column=0, columnspan=4, sticky="w", pady=4
        )
        self.recorder_ready_text = StringVar()
        self.recorder_ready_checkbutton = ttk.Checkbutton(
            recorder_tab,
            textvariable=self.recorder_ready_text,
            variable=self.recorder_ready,
        )
        self.recorder_ready_checkbutton.grid(row=7, column=0, columnspan=4, sticky="w", pady=4)
        ttk.Checkbutton(
            recorder_tab,
            text="已完成所选正式任务的指导与必要练习",
            variable=self.practice_ready,
        ).grid(row=8, column=0, columnspan=4, sticky="w", pady=4)
        self.scan_streams_button = ttk.Button(recorder_tab, text="自动扫描 LSL 数据流", command=self.check_lsl_streams)
        self.scan_streams_button.grid(
            row=9,
            column=0,
            sticky="w",
            pady=(12, 4),
        )
        ttk.Label(recorder_tab, textvariable=self.stream_check_status, wraplength=760).grid(
            row=9,
            column=1,
            columnspan=3,
            sticky="w",
            padx=(12, 0),
            pady=(12, 4),
        )
        audio_column = 0
        if sys.platform == "darwin":
            ttk.Button(recorder_tab, text="打开 LabRecorder（兼容模式）", command=self.open_labrecorder).grid(
                row=10,
                column=0,
                sticky="w",
                pady=(8, 0),
            )
            audio_column = 1
        ttk.Button(recorder_tab, text="试听过渡提示音", command=self.test_audio_cue).grid(
            row=10,
            column=audio_column,
            sticky="w",
            padx=(12, 0) if audio_column else 0,
            pady=(8, 0),
        )
        ttk.Label(recorder_tab, text="正式采集时仅在过渡边界播放，并同步写入 Marker。", foreground="#7a4b00").grid(
            row=10,
            column=2,
            columnspan=2,
            sticky="w",
            padx=(12, 0),
            pady=(8, 0),
        )
        recorder_tab.columnconfigure(1, weight=1)
        recorder_tab.columnconfigure(3, weight=1)
        self._update_recording_mode_controls()

        ttk.Label(self.setup_frame, textvariable=self.estimate_text).grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 2))
        ttk.Label(self.setup_frame, textvariable=self.selection_warning, foreground="#9a5a00").grid(
            row=4,
            column=0,
            columnspan=4,
            sticky="w",
        )
        ttk.Label(self.setup_frame, textvariable=self.setup_error, foreground="#b00020", wraplength=960).grid(
            row=5,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(3, 0),
        )
        ttk.Separator(self.setup_frame).grid(row=6, column=0, columnspan=4, sticky="ew", pady=8)
        ttk.Label(self.setup_frame, textvariable=self.status).grid(row=7, column=0, columnspan=4, sticky="w")

        ttk.Button(self.setup_frame, text="发送测试 Marker", command=self.send_test_marker).grid(
            row=8, column=0, sticky="w", pady=(12, 0)
        )
        ttk.Button(self.setup_frame, text="打开实时监测", command=self.open_live_monitor).grid(
            row=8, column=1, sticky="w", pady=(12, 0)
        )
        ttk.Button(self.setup_frame, text="开始所选模块", command=self.start_experiment).grid(
            row=8, column=3, sticky="e", pady=(12, 0)
        )

        self.setup_frame.columnconfigure(1, weight=1)
        self.setup_frame.columnconfigure(3, weight=1)
        self.setup_frame.rowconfigure(2, weight=1)
        self._update_estimate()

    def _selected_modules(self) -> list[str]:
        return [protocol.task for protocol in PROTOCOLS if self.module_vars[protocol.task].get()]

    def _module_selection_changed(self) -> None:
        self.acquisition_batch.set(CUSTOM_ACQUISITION_BATCH)
        self._update_acquisition_batch_detail()
        self.practice_ready.set(False)
        self._update_estimate()

    def _update_acquisition_batch_detail(self) -> None:
        preset = ACQUISITION_BATCH_PRESETS.get(self.acquisition_batch.get())
        detail = (
            preset[2] + " 预设会自动关闭短流程；跨日采集请更换 Session。"
            if preset is not None
            else "自由选择模块；正式任务建议包含 M0，跨日采集请更换 Session。"
        )
        self.acquisition_batch_detail.set(detail)

    def _apply_acquisition_batch(self, _event: object | None = None) -> None:
        preset = ACQUISITION_BATCH_PRESETS.get(self.acquisition_batch.get())
        if preset is not None:
            selected_tasks = set(preset[1])
            if self.skip_m0.get():
                selected_tasks.discard("m0_baseline")
            for task, variable in self.module_vars.items():
                variable.set(task in selected_tasks)
            self.short_protocol.set(False)
            self.practice_ready.set(False)
        self._update_acquisition_batch_detail()
        self._update_estimate()

    def _skip_m0_changed(self) -> None:
        if self.acquisition_batch.get() in ACQUISITION_BATCH_PRESETS:
            self._apply_acquisition_batch()
        else:
            self._update_estimate()

    def _practice_config_changed(self, _event: object | None = None) -> None:
        self.practice_ready.set(False)
        self._update_estimate()

    def _update_estimate(self) -> None:
        selected = self._selected_modules()
        seconds = sum(
            estimate_protocol_seconds(
                task,
                short=self.short_protocol.get(),
                older_adult=self.older_adult.get(),
            )
            for task in selected
        )
        manual_note = ""
        for task in selected:
            plan = build_protocol_plan(
                task,
                short=self.short_protocol.get(),
                older_adult=self.older_adult.get(),
                target_object=self.target_object.get(),
            )
            if any(step.advance in {"operator", "form"} for step in plan):
                manual_note = "（另含人工确认/问卷时间）"
                break
        self.estimate_text.set(f"已选 {len(selected)} 个模块，自动计时约 {seconds / 60:.1f} 分钟{manual_note}")
        physiological_tasks = {
            task
            for task in selected
            if task not in {"deviceqc", "m0_baseline", "m5_debrief", "m6_readiness"}
        }
        missing_baseline = (
            "m0_baseline" not in selected and bool(physiological_tasks) and not self.skip_m0.get()
        )
        warnings: list[str] = []
        if missing_baseline:
            warnings.append("提示：未选择 M0，本会话正式任务将缺少个体基线。")
        if "m2_nback" in selected and self.nback_feedback.get() and not self.short_protocol.get():
            warnings.append("提示：正式 M2 已启用正误颜色反馈；这会改变视觉刺激与任务策略，建议关闭。")
        if (
            "m2_nback" in selected
            and self.nback_order.get().startswith("由易到难")
            and not self.short_protocol.get()
        ):
            warnings.append("提示：M2 由易到难会把负荷等级与时间/疲劳混杂；正式组间比较建议改用拉丁方平衡。")
        self.selection_warning.set("；".join(warnings))

    def open_live_monitor(self) -> None:
        monitor = self.live_monitor
        if monitor is not None and monitor.window.winfo_exists():
            monitor.window.lift()
            monitor.window.focus_force()
            return
        from .monitor import LiveMonitorWindow

        self.live_monitor = LiveMonitorWindow(Toplevel(self.root))

    def check_lsl_streams(self) -> None:
        self.scan_streams_button.configure(state="disabled")
        self.stream_check_status.set("正在扫描，请保持 BioMultiLite LSL 为 Start 状态……")

        def scan() -> None:
            error: Exception | None = None
            found: set[str] = set()
            try:
                from pylsl import resolve_streams

                for info in resolve_streams(2.0):
                    descriptor = describe_stream(info)
                    if descriptor is not None:
                        found.add(descriptor.kind)
            except Exception as caught:  # noqa: BLE001 - reported inline on the setup page
                error = caught
            self._post_to_ui(lambda found=found, error=error: self._lsl_scan_finished(found, error))

        threading.Thread(target=scan, daemon=True).start()

    def open_labrecorder(self) -> None:
        try:
            app_path = launch_labrecorder()
        except (FileNotFoundError, OSError, RuntimeError) as error:
            self.stream_check_status.set(f"LabRecorder 启动失败：{error}")
            return
        self.stream_check_status.set(f"已打开 LabRecorder：{app_path}")

    def test_audio_cue(self) -> None:
        if not audio_cues_supported():
            self.stream_check_status.set("当前系统缺少可用的系统提示音播放器。")
            return
        if not self.audio_enabled.get():
            self.stream_check_status.set("请先勾选“启用中文女声过渡提示”。")
            return
        play_audio_cue("close_eyes")
        self.stream_check_status.set("已播放闭眼中文女声试听；请确认音量舒适且被试能够听见。")

    def _lsl_scan_finished(self, found: set[str], error: Exception | None) -> None:
        self.scan_streams_button.configure(state="normal")
        if error is not None:
            self.streams_ready.set(False)
            self.stream_check_status.set(f"扫描失败：{error}")
            return
        missing = [kind for kind in SUPPORTED_STREAM_KINDS if kind not in found]
        found_labels = "、".join(STREAM_KIND_LABELS[kind] for kind in SUPPORTED_STREAM_KINDS if kind in found)
        if missing:
            missing_labels = "、".join(STREAM_KIND_LABELS[kind] for kind in missing)
            self.streams_ready.set(False)
            self.stream_check_status.set(f"已发现：{found_labels or '无'}；缺少：{missing_labels}")
            return
        self.streams_ready.set(True)
        self.stream_check_status.set(f"六类数值流已就绪：{found_labels}。开始录制时还会检查两条 Marker 流。")

    def _build_task_view(self) -> None:
        self.task_frame = Frame(self.root, bg=TASK_BG, padx=40, pady=28)
        style = ttk.Style(self.root)
        style.configure("Task.TButton", font=(UI_FONT_FAMILY, 16, "bold"), padding=(20, 14))
        style.configure("Quality.TButton", font=(UI_FONT_FAMILY, 14, "bold"), padding=(16, 12))
        style.configure(
            "Task.Horizontal.TProgressbar",
            troughcolor="#232c38",
            background=TASK_ACCENT,
            bordercolor=TASK_BG,
            lightcolor=TASK_ACCENT,
            darkcolor=TASK_ACCENT,
        )

        header = Frame(self.task_frame, bg=TASK_BG)
        header.pack(fill="x")
        self.module_header_label = Label(
            header,
            text="",
            bg=TASK_BG,
            fg=TASK_FG,
            font=(UI_FONT_FAMILY, 15, "bold"),
        )
        self.module_header_label.pack(anchor="w")
        self.progress_label = Label(
            header,
            text="",
            bg=TASK_BG,
            fg=TASK_MUTED_FG,
            font=(UI_FONT_FAMILY, 13),
        )
        self.progress_label.pack(anchor="w", pady=(4, 0))
        self.module_progress = ttk.Progressbar(
            header,
            style="Task.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
            value=0,
        )
        self.module_progress.pack(fill="x", pady=(8, 0))
        self.task_signal_label = Label(
            header,
            textvariable=self.task_signal_status,
            bg=TASK_BG,
            fg=TASK_MUTED_FG,
            font=(UI_FONT_FAMILY, 12, "bold"),
        )
        self.task_signal_label.pack(anchor="w", pady=(8, 0))
        Label(
            header,
            text="状态条检查断流、采样率、恒定通道与 EEG 削顶；M1 检测到明显动作时会自动写入复核标记。",
            bg=TASK_BG,
            fg="#5c6a7a",
            font=(UI_FONT_FAMILY, 10),
        ).pack(anchor="w", pady=(2, 0))

        self.task_content = Frame(self.task_frame, bg=TASK_BG)
        self.task_content.pack(fill="both", expand=True, pady=(12, 0))
        self.image_label = Label(self.task_content, bg=TASK_BG)
        self.image_label.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.image_label.grid_remove()
        self.cue_label = Label(
            self.task_content,
            text="",
            bg=TASK_BG,
            fg=TASK_FG,
            font=(UI_FONT_FAMILY, 54, "bold"),
            wraplength=1100,
            justify="center",
        )
        self.cue_label.grid(row=1, column=0, sticky="nsew", pady=4)
        self.default_cue_foreground = TASK_FG
        self.detail_label = Label(
            self.task_content,
            text="",
            bg=TASK_BG,
            fg=TASK_MUTED_FG,
            font=(UI_FONT_FAMILY, 22),
            wraplength=1050,
            justify="center",
        )
        self.detail_label.grid(row=2, column=0, sticky="ew", pady=8)
        self.form_frame = ttk.LabelFrame(self.task_content, text="请填写", padding=18)
        self.form_frame.grid(row=3, column=0, sticky="ew", padx=100, pady=8)
        self.form_frame.grid_remove()
        self.countdown_label = Label(
            self.task_content,
            text="",
            bg=TASK_BG,
            fg=TASK_ACCENT,
            font=(UI_FONT_FAMILY, 30, "bold"),
        )
        self.countdown_label.grid(row=4, column=0, sticky="ew", pady=8)
        self.task_content.columnconfigure(0, weight=1)
        self.task_content.rowconfigure(1, weight=1)

        self.quality_frame = Frame(self.task_frame, bg=TASK_BG)
        self.quality_frame.pack(fill="x", pady=(4, 0))
        for label, event, code in (
            ("标记试次无效", "trial_invalid", 900),
            ("记录设备调整", "device_adjustment", 901),
            ("记录信号中断", "bluetooth_interruption", 902),
        ):
            ttk.Button(
                self.quality_frame,
                text=label,
                style="Quality.TButton",
                takefocus=False,
                command=lambda event=event, code=code: self._send_quality_marker(event, code),
            ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Button(
            self.quality_frame,
            text="查看实时波形",
            style="Quality.TButton",
            takefocus=False,
            command=self.open_live_monitor,
        ).pack(side="left", fill="x", expand=True)
        self.quality_frame.pack_forget()

        self.button_frame = Frame(self.task_frame, bg=TASK_BG)
        self.button_frame.pack(fill="x", pady=(10, 0))
        self.action_button = ttk.Button(
            self.button_frame,
            text="继续",
            style="Task.TButton",
            takefocus=False,
            command=self._complete_manual_step,
        )
        self.action_button.pack(side="left")
        self.action_button.pack_forget()
        self.secondary_button = ttk.Button(
            self.button_frame,
            text="返回首页",
            style="Task.TButton",
            takefocus=False,
            command=self._return_to_setup,
        )
        self.secondary_button.pack(side="left", padx=(12, 0))
        self.secondary_button.pack_forget()
        self.abort_button = ttk.Button(
            self.button_frame,
            text="中止实验 (Esc)",
            style="Task.TButton",
            takefocus=False,
            command=self.abort_experiment,
        )
        self.abort_button.pack(side="right")
        self._load_object_images()

    def _update_task_signal_status(self) -> None:
        self.task_signal_poll_id = None
        parts: list[str] = []
        status_by_kind: dict[str, str] = {}
        has_error = False
        waiting = False
        motion_warning: tuple[Step, float, float] | None = None
        manager_errors = self.task_signal_manager.errors()
        for kind in TASK_SIGNAL_KINDS:
            label = STREAM_KIND_LABELS[kind]
            window = self.task_signal_manager.window(kind, 3.0, max_points=240)
            if window is None or len(window.samples) < 2:
                parts.append(f"{label} ○等待")
                status_by_kind[kind] = "waiting"
                waiting = True
                continue
            if not window.is_live:
                parts.append(f"{label} ✕中断")
                status_by_kind[kind] = "interrupted"
                has_error = True
                continue
            rate = window.observed_srate
            rate_text = f"{rate:.1f}Hz" if rate is not None else "已连接"
            flat_count = flat_channel_count(window)
            if flat_count:
                parts.append(f"{label} !恒定{flat_count}ch/{rate_text}")
                status_by_kind[kind] = "flat"
                has_error = True
            elif kind == "eeg" and (clipped_count := eeg_clipped_channel_count(window)):
                parts.append(f"{label} !削顶{clipped_count}ch/{rate_text}")
                status_by_kind[kind] = "clipped"
                has_error = True
            elif (
                kind == "motion"
                and self.active
                and not self.stopping
                and 0 <= self.step_index < len(self.plan)
                and self.plan[self.step_index].event in {"mi_left", "mi_right", "mi_idle"}
                and time.monotonic() - self.step_started >= 0.5
            ):
                recent_motion = self.task_signal_manager.window("motion", 0.75, max_points=100)
                detected, accel_span, gyro_span = (
                    motion_activity_metrics(recent_motion) if recent_motion is not None else (False, 0.0, 0.0)
                )
                if detected:
                    parts.append(f"{label} !M1动作/{rate_text}")
                    status_by_kind[kind] = "motion"
                    has_error = True
                    motion_warning = (self.plan[self.step_index], accel_span, gyro_span)
                else:
                    parts.append(f"{label} ●{rate_text}")
                    status_by_kind[kind] = "ready"
            else:
                parts.append(f"{label} ●{rate_text}")
                status_by_kind[kind] = "ready"
        if manager_errors:
            has_error = True
            parts.append("采集器 !异常")
        self.task_signal_status.set("信号状态：" + "  |  ".join(parts))
        foreground = "#b42318" if has_error else "#9a6700" if waiting else "#14804a"
        self.task_signal_label.configure(foreground=foreground)
        if motion_warning is not None and self.motion_warning_generation != self.step_generation:
            step, accel_span, gyro_span = motion_warning
            self.motion_warning_generation = self.step_generation
            self._push_step_marker(
                "mi_motion_warning",
                903,
                step,
                acceleration_span=round(accel_span, 6),
                gyroscope_span=round(gyro_span, 6),
                quality_status="requires_offline_review",
                invalidates_trial=False,
            )
        if (
            self.active
            and not self.stopping
            and self.current_task == "m6_readiness"
            and 0 <= self.step_index < len(self.plan)
            and self.plan[self.step_index].event
            in {"readiness_signal_gate_start", "readiness_baseline_start", "sart_stimulus"}
        ):
            self.readiness_quality_samples += 1
            eeg_status = status_by_kind.get("eeg", "waiting")
            if eeg_status != "ready" or manager_errors:
                self.readiness_quality_bad_samples += 1
                self.readiness_quality_issues.add(f"eeg_{eeg_status}")
                if manager_errors:
                    self.readiness_quality_issues.add("stream_manager_error")
        if self.root.winfo_exists():
            self.task_signal_poll_id = self.root.after(500, self._update_task_signal_status)

    def _load_object_images(self) -> None:
        for object_name, filename in OBJECT_ASSETS.items():
            try:
                image = PhotoImage(file=str(object_asset_path(filename)))
                factor = max(1, (max(image.width(), image.height()) + 419) // 420)
                self.object_images[object_name] = image.subsample(factor, factor)
            except Exception:  # noqa: BLE001 - missing visuals fall back to large text cues
                continue

    @staticmethod
    def _cue_font_size(text: str, has_image: bool) -> int:
        if has_image:
            return 44
        if len(text) <= 3:
            return 108
        if len(text) <= 10:
            return 64
        return 48

    def _display_visual(self, visual: str | None) -> bool:
        image = self.object_images.get(visual or "")
        if image is None:
            self.image_label.configure(image="")
            self.image_label.grid_remove()
            return False
        self.image_label.configure(image=image)
        self.image_label.grid()
        return True

    def _hide_inline_form(self) -> None:
        self.form_frame.grid_remove()
        self.form_variables = {}
        self.form_error.set("")

    def _show_inline_form(self, step: Step) -> None:
        for child in self.form_frame.winfo_children():
            child.destroy()
        self.form_variables = {}
        self.form_error.set("")
        for row, field in enumerate(step.fields):
            ttk.Label(self.form_frame, text=field.label, font=(UI_FONT_FAMILY, 16)).grid(
                row=row,
                column=0,
                sticky="w",
                padx=(0, 18),
                pady=7,
            )
            variable = StringVar(value="")
            self.form_variables[field.key] = variable
            if field.kind == "rating":
                values = tuple(str(value) for value in range(field.minimum or 1, (field.maximum or 10) + 1))
            elif field.kind == "boolean":
                values = ("否", "是")
            else:
                values = field.choices
            ttk.Combobox(
                self.form_frame,
                textvariable=variable,
                values=values,
                state="readonly",
                font=(UI_FONT_FAMILY, 15),
            ).grid(row=row, column=1, sticky="ew", pady=7)
        ttk.Label(self.form_frame, textvariable=self.form_error, foreground="#b00020").grid(
            row=len(step.fields),
            column=0,
            columnspan=2,
            sticky="w",
            pady=(6, 0),
        )
        self.form_frame.columnconfigure(1, weight=1)
        self.form_frame.grid()

    def _read_inline_form(self, fields: tuple[InputField, ...]) -> dict[str, object] | None:
        responses: dict[str, object] = {}
        for field in fields:
            value = self.form_variables[field.key].get()
            if not value:
                self.form_error.set(f"请填写：{field.label}")
                return None
            if field.kind == "rating":
                responses[field.key] = int(value)
            elif field.kind == "boolean":
                responses[field.key] = value == "是"
            else:
                responses[field.key] = value
        self.form_error.set("")
        return responses

    def _show_task_action(
        self,
        title: str,
        detail: str,
        primary_text: str,
        primary_command: Callable[[], None],
        *,
        secondary_text: str | None = None,
        secondary_command: Callable[[], None] | None = None,
        allow_abort: bool = False,
    ) -> None:
        self._hide_inline_form()
        self._display_visual(None)
        self.cue_label.configure(
            text=title,
            font=(UI_FONT_FAMILY, 48, "bold"),
            foreground=self.default_cue_foreground,
        )
        self.detail_label.configure(text=detail)
        self.countdown_label.configure(text="")
        self.action_button.configure(text=primary_text, command=primary_command, state="normal")
        self.action_button.pack(side="left")
        if secondary_text is not None and secondary_command is not None:
            self.secondary_button.configure(text=secondary_text, command=secondary_command)
            self.secondary_button.pack(side="left", padx=(12, 0))
        else:
            self.secondary_button.pack_forget()
        if allow_abort:
            self.abort_button.pack(side="right")
        else:
            self.abort_button.pack_forget()
        self.quality_frame.pack_forget()

    def _send_quality_marker(self, event: str, code: int) -> None:
        if not self.active or self.stopping:
            return
        step = self.plan[self.step_index] if 0 <= self.step_index < len(self.plan) else None
        payload = {
            "code": code,
            "event": event,
            "block": step.block if step is not None else None,
            "trial": step.trial if step is not None else None,
            **self.current_context,
            "app_version": APP_VERSION,
            "unix_time": time.time(),
        }
        self._push_marker(payload)
        self.progress_label.configure(text=f"已记录：{event}  |  步骤 {self.step_index + 1}/{len(self.plan)}")
        self.task_frame.focus_set()

    def _collect_base_context(self) -> tuple[dict[str, str], Path]:
        participant = validate_identifier(self.participant.get(), "被试编号")
        session = validate_identifier(self.session.get(), "会话编号")
        run = validate_identifier(self.run.get(), "Run 编号")
        output_text = self.output_root.get().strip()
        if not output_text:
            raise ValueError("数据目录不能为空")
        return {"participant": participant, "session": session, "run": run}, Path(output_text)

    def _collect_participant_profile(self) -> dict[str, object]:
        return validate_participant_profile(
            name=self.participant_name.get(),
            age=self.participant_age.get(),
            sex=self.participant_sex.get(),
            education_years=self.education_years.get(),
            dominant_hand=self.dominant_hand.get(),
        )

    def _show_setup_error(self, message: str, tab_index: int) -> None:
        self.setup_error.set(message)
        self.setup_notebook.select(tab_index)

    @staticmethod
    def _paths_for_task(context: dict[str, str], output_root: Path, task: str) -> tuple[str, Path, Path, Path]:
        filename = build_xdf_filename(context["participant"], context["session"], task, context["run"])
        log_dir = output_root / "logs"
        return (
            filename,
            output_root.resolve() / filename,
            log_dir / filename.replace(".xdf", "_events.jsonl"),
            log_dir / filename.replace(".xdf", "_recorder.jsonl"),
        )

    @staticmethod
    def _protocol_seed(context: dict[str, str], task: str) -> int:
        seed_text = ":".join((context["participant"], context["session"], context["run"], task))
        return int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:4], "big")

    def send_test_marker(self) -> None:
        try:
            context, _ = self._collect_base_context()
        except ValueError as error:
            self._show_setup_error(str(error), 0)
            return
        self.setup_error.set("")
        payload = {
            "code": 1,
            "event": "marker_test",
            **context,
            "task": "connectiontest",
            "app_version": APP_VERSION,
            "unix_time": time.time(),
        }
        timestamp = self._push_marker(payload)
        self.status.set(f"已发送 marker_test，LSL 时间戳 {timestamp:.6f}")

    def start_experiment(self) -> None:
        if self.active:
            return
        self.setup_error.set("")
        try:
            context, output_root = self._collect_base_context()
            profile = self._collect_participant_profile()
        except (ValueError, OSError) as error:
            self._show_setup_error(str(error), 0)
            return
        try:
            port: int | None = None
            if self.recording_mode.get() == RECORDING_MODE_RCS:
                port = int(self.rcs_port.get())
                if not 1 <= port <= 65535:
                    raise ValueError("RCS 端口范围应为 1-65535")
        except (ValueError, OSError) as error:
            self._show_setup_error(str(error), 2)
            return
        self.validated_rcs_port = port

        if not self.consent_confirmed.get():
            self._show_setup_error("请确认已获得知情同意且资料录入准确。", 0)
            return

        selected = self._selected_modules()
        if not selected:
            self._show_setup_error("请至少选择一个实验模块。", 1)
            return
        preset = ACQUISITION_BATCH_PRESETS.get(self.acquisition_batch.get())
        expected_tasks = preset[1] if preset is not None else None
        if expected_tasks is not None and self.skip_m0.get():
            expected_tasks = tuple(task for task in expected_tasks if task != "m0_baseline")
        if preset is not None and tuple(selected) == expected_tasks:
            self.active_acquisition_batch_id = preset[0]
        else:
            self.active_acquisition_batch_id = "custom"
            if preset is not None:
                self.acquisition_batch.set(CUSTOM_ACQUISITION_BATCH)
                self._update_acquisition_batch_detail()
        if not all((self.operator_ready.get(), self.streams_ready.get(), self.recorder_ready.get())):
            self._show_setup_error("请完成“录制检查”页的前三项开始前确认。", 2)
            return
        practice_tasks = {"m1_mi", "m2_nback", "m4a_intent", "m4b_target"}
        if any(task in practice_tasks for task in selected) and not self.practice_ready.get():
            self._show_setup_error("所选任务需要先完成指导与练习，请在“录制检查”页确认。", 2)
            return

        existing: list[Path] = []
        for task in selected:
            filename, target_path, log_path, recorder_log_path = self._paths_for_task(context, output_root, task)
            existing.extend(path for path in (target_path, log_path) if path.exists())
        if existing:
            self._show_setup_error(
                "目标文件已存在，请更换 Run 编号：" + "；".join(str(path) for path in existing),
                0,
            )
            return

        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / "logs").mkdir(parents=True, exist_ok=True)
        try:
            profile_path, profile_created = save_participant_profile(
                output_root,
                context["participant"],
                context["session"],
                profile,
                APP_VERSION,
            )
        except ValueError as error:
            self._show_setup_error(str(error), 0)
            return
        profile_status = "已创建" if profile_created else "已核对"
        self.status.set(f"被试资料{profile_status}：{profile_path.name}；正在启动录制")
        self.base_context = context
        self.output_directory = output_root
        self.module_queue = selected
        self.module_index = 0
        self._begin_current_module(port)

    def _begin_current_module(self, port: int | None = None) -> None:
        task = self.module_queue[self.module_index]
        filename, target_path, log_path, recorder_log_path = self._paths_for_task(
            self.base_context,
            self.output_directory,
            task,
        )
        seed = self._protocol_seed(self.base_context, task)
        self.event_log_path = log_path
        self.recorder_log_path = recorder_log_path
        self.xdf_path = target_path
        self.current_task = task
        self.current_context = {
            **self.base_context,
            "task": task,
            "protocol_seed": seed,
            "module_index": self.module_index + 1,
            "module_count": len(self.module_queue),
            "module_sequence": self.module_queue,
            "acquisition_batch": self.active_acquisition_batch_id,
            "m0_skipped": bool(self.skip_m0.get() and "m0_baseline" not in self.module_queue),
            "short_protocol": self.short_protocol.get(),
            "older_adult_timing": self.older_adult.get(),
        }
        nback_order = "counterbalanced" if self.nback_order.get().startswith("拉丁方") else "ascending"
        if task == "m2_nback":
            self.current_context["nback_order"] = nback_order
            self.current_context["nback_feedback_enabled"] = self.nback_feedback.get()
        self.plan = build_protocol_plan(
            task,
            short=self.short_protocol.get(),
            older_adult=self.older_adult.get(),
            seed=seed,
            target_object=self.target_object.get(),
            nback_order=nback_order,
        )
        self.step_index = -1
        self.active = True
        self.stopping = False
        self.current_response_time = None
        self.block_results = {}
        self.readiness_trials = []
        self.readiness_result = None
        self.readiness_quality_samples = 0
        self.readiness_quality_bad_samples = 0
        self.readiness_quality_issues = set()
        self.pending_next_task = None
        self.recorder_started = False
        self.xdf_initial_size = 0
        self.xdf_current_size = 0
        self.last_file_poll = 0.0

        self.setup_frame.pack_forget()
        self.task_frame.pack(fill="both", expand=True)
        self.root.attributes("-fullscreen", True)
        self.cue_label.configure(text="正在准备录制", foreground=self.default_cue_foreground)
        self.module_header_label.configure(
            text=f"{PROTOCOL_BY_TASK[task].title}｜第 {self.module_index + 1}/{len(self.module_queue)} 模块"
        )
        self.module_progress.configure(maximum=len(self.plan), value=0)
        self.detail_label.configure(
            text=f"{PROTOCOL_BY_TASK[task].title}（{self.module_index + 1}/{len(self.module_queue)}）\n"
            "正在订阅 LSL 流并创建 XDF 文件"
        )
        self.countdown_label.configure(text="")
        self.progress_label.configure(text=f"输出文件：{filename}")
        self._hide_inline_form()
        self._display_visual(None)
        self.quality_frame.pack_forget()
        self.action_button.pack_forget()
        self.secondary_button.pack_forget()
        self.abort_button.pack(side="right")

        mode = self.recording_mode.get()
        if mode != RECORDING_MODE_MANUAL:
            if mode == RECORDING_MODE_EMBEDDED:
                client: LabRecorderClient | EmbeddedRecorderClient = EmbeddedRecorderClient()
            else:
                if port is None:
                    port = self.validated_rcs_port
                if port is None:
                    self._show_saving_state()
                    self._stop_and_return(aborted=True)
                    return
                client = LabRecorderClient(self.rcs_host.get().strip(), port)

            def prepare() -> None:
                try:
                    xdf_path, initial_size = client.start_recording(self.output_directory, filename)
                except Exception as error:  # noqa: BLE001 - surfaced to the operator
                    if self.recorder_log_path is not None:
                        client._record_diagnostic("recording_start_failed", error=str(error))
                        client.write_diagnostics(self.recorder_log_path)
                    self._post_to_ui(lambda error=error: self._prepare_failed(error))
                    return
                if self.recorder_log_path is not None:
                    client.write_diagnostics(self.recorder_log_path)
                self._post_to_ui(lambda: self._recording_ready(client, xdf_path, initial_size))

            threading.Thread(target=prepare, daemon=True).start()
        else:
            self.root.after(500, self._manual_recording_ready)

    def _prepare_failed(self, error: Exception) -> None:
        if not self.active or self.stopping:
            return
        self.status.set(f"无法启动录制：{error}")
        self.active = False
        self._close_current_files()
        detail = (
            "请确认所有 LSL 流已启动、网络可达且目标目录可写。"
            if self.recording_mode.get() == RECORDING_MODE_EMBEDDED
            else "请确认 RCS 配置、目标目录权限，并检查 LabRecorder 当前未在录制。"
        )
        self._show_task_action(
            "录制启动失败",
            f"{error}\n\n{detail}",
            "返回首页检查",
            self._return_to_setup,
        )

    def _recording_ready(
        self,
        client: LabRecorderClient | EmbeddedRecorderClient,
        xdf_path: Path,
        initial_size: int,
    ) -> None:
        if not self.active or self.stopping:
            try:
                client.stop_recording(xdf_path)
            except Exception:  # noqa: BLE001 - best-effort cleanup after UI cancellation
                pass
            return
        self.recorder_started = True
        self._recorder_client = client
        assert self.event_log_path is not None
        self.log_handle = self.event_log_path.open("x", encoding="utf-8")
        self.xdf_path = xdf_path
        self.xdf_initial_size = initial_size
        self.xdf_current_size = initial_size
        self.cue_label.configure(text="录制已启动")
        self.detail_label.configure(text=f"已验证 XDF：{initial_size / 1024:.1f} KB，实验将在 2 秒后开始")
        self.abort_button.pack(side="right")
        self.root.after(2000, self._advance_step)

    def _manual_recording_ready(self) -> None:
        if not self.active or self.stopping:
            return
        self._show_task_action(
            "请开始手动录制",
            "在 LabRecorder 中点击 Start，确认计时已经开始后，再点击下方按钮。",
            "已开始，验证 XDF",
            self._confirm_manual_recording_started,
            allow_abort=False,
        )

    def _confirm_manual_recording_started(self) -> None:
        if not self.active or self.stopping:
            return
        self.action_button.pack_forget()
        self.secondary_button.pack_forget()
        self.cue_label.configure(text="正在验证 XDF")
        self.detail_label.configure(text="请稍候")

        def verify_manual() -> None:
            try:
                assert self.xdf_path is not None
                initial_size = LabRecorderClient.wait_for_xdf(self.xdf_path)
            except Exception as error:  # noqa: BLE001 - surfaced to the operator
                self._post_to_ui(lambda error=error: self._prepare_failed(error))
                return
            self._post_to_ui(lambda: self._manual_xdf_ready(initial_size))

        threading.Thread(target=verify_manual, daemon=True).start()

    def _manual_xdf_ready(self, initial_size: int) -> None:
        if not self.active or self.stopping:
            return
        self.xdf_initial_size = initial_size
        self.xdf_current_size = initial_size
        assert self.event_log_path is not None
        self.log_handle = self.event_log_path.open("x", encoding="utf-8")
        self.cue_label.configure(text="录制已启动")
        self.detail_label.configure(text=f"已验证 XDF：{initial_size / 1024:.1f} KB，实验将在 2 秒后开始")
        self.abort_button.pack(side="right")
        self.root.after(2000, self._advance_step)

    def _create_readiness_assessment(self, expected_trials: int) -> dict[str, object]:
        quality_bad_rate = (
            self.readiness_quality_bad_samples / self.readiness_quality_samples
            if self.readiness_quality_samples
            else 1.0
        )
        signal_quality_ok = self.readiness_quality_samples > 0 and quality_bad_rate <= 0.1
        result = assess_readiness(
            self.current_context,
            self.readiness_trials,
            expected_trials=expected_trials,
            signal_quality_ok=signal_quality_ok,
            signal_quality_issues=self.readiness_quality_issues,
        )
        result["signal_quality_sample_count"] = self.readiness_quality_samples
        result["signal_quality_bad_sample_count"] = self.readiness_quality_bad_samples
        result["signal_quality_bad_rate"] = round(quality_bad_rate, 6)
        return result

    @staticmethod
    def _readiness_result_detail(result: dict[str, object]) -> str:
        return (
            f"{result.get('recommendation', '')}\n\n"
            f"{result.get('disclaimer', '')}\n"
            "管理端只应接收本次状态等级；原始脑信号和明细指标不得用于惩罚或永久能力画像。"
        )

    def _advance_step(self) -> None:
        if not self.active or self.stopping:
            return
        self.step_generation += 1
        self.step_completion_started = False
        self.step_index += 1
        if self.step_index >= len(self.plan):
            self._finish_experiment()
            return

        step = self.plan[self.step_index]
        self.step_started = time.monotonic()
        self.current_response_time = None
        self.step_text_replaced = False
        self.audio_warning_played = False
        self._hide_inline_form()
        has_image = self._display_visual(step.visual)
        self.cue_label.configure(
            text=step.text,
            font=(UI_FONT_FAMILY, self._cue_font_size(step.text, has_image), "bold"),
            foreground=self.default_cue_foreground,
        )
        self.detail_label.configure(text=step.detail)
        self.progress_label.configure(text=f"步骤 {self.step_index + 1}/{len(self.plan)}")
        self.module_progress.configure(value=self.step_index + 1)
        self.action_button.pack_forget()
        self.action_button.configure(state="disabled")
        self.secondary_button.pack_forget()
        self.abort_button.pack(side="right")
        self.quality_frame.pack(before=self.button_frame, fill="x", pady=(4, 0))
        if step.event == "readiness_assessment":
            expected_trials = int(step.metadata.get("expected_trials", len(self.readiness_trials)))
            self.readiness_result = self._create_readiness_assessment(expected_trials)
            status_colors = {
                "normal": "#14804a",
                "retest": "#9a6700",
                "rest": "#b42318",
                "unable": "#59636e",
            }
            self.cue_label.configure(
                text=str(self.readiness_result["label"]),
                font=(UI_FONT_FAMILY, 64, "bold"),
                foreground=status_colors.get(str(self.readiness_result["status"]), self.default_cue_foreground),
            )
            self.detail_label.configure(text=self._readiness_result_detail(self.readiness_result))
            self._push_step_marker(
                step.event,
                step.code,
                step,
                assessment=self.readiness_result,
            )
        elif step.event is not None:
            self._push_step_marker(step.event, step.code, step)
        if step.start_sound is not None:
            self._play_audio_cue(step.start_sound, step, "start")
        if step.advance == "timed":
            self.task_frame.focus_set()
            self._tick_step(self.step_generation, self.step_index)
            return
        if step.advance == "form":
            self._show_inline_form(step)
            self.countdown_label.configure(text="请完成表单")
        else:
            self.countdown_label.configure(text="等待实验员确认")
        self.action_button.configure(
            text="提交表单并继续" if step.advance == "form" else "已完成，继续",
            command=self._complete_manual_step,
            state="normal",
        )
        self.action_button.pack(side="left")

    def _push_step_marker(
        self,
        event: str,
        code: int | None,
        step: Step,
        **extra: object,
    ) -> float:
        return self._push_marker(
            {
                "code": code,
                "event": event,
                "block": step.block,
                "trial": step.trial,
                **step.metadata,
                **extra,
                **self.current_context,
                "app_version": APP_VERSION,
                "unix_time": time.time(),
            }
        )

    def _play_audio_cue(self, cue: str, step: Step, phase: str) -> None:
        if not self.audio_enabled.get() or not audio_cues_supported():
            return
        self._push_step_marker(
            "audio_cue",
            700,
            step,
            audio_cue=cue,
            audio_phase=phase,
            audio_text=VOICE_CUE_TEXTS[cue],
            audio_voice=VOICE_CUE_VOICE,
        )
        play_audio_cue(cue)

    def _on_response_key(self, _event: object) -> str | None:
        if not self.active or self.stopping or not 0 <= self.step_index < len(self.plan):
            return None
        step = self.plan[self.step_index]
        if step.response_key != "space":
            return None
        if self.current_response_time is not None:
            return "break"
        self.current_response_time = time.monotonic()
        elapsed = self.current_response_time - self.step_started
        should_respond = bool(step.metadata.get("should_respond", step.metadata.get("is_target")))
        false_start_threshold = step.metadata.get("false_start_threshold_s")
        false_start = bool(
            isinstance(false_start_threshold, (int, float)) and elapsed < float(false_start_threshold)
        )
        correct = should_respond and not false_start
        # 反馈只在字母仍显示时给出；进入注视十字阶段后按键不再覆盖 "+",
        # 保证每个试次末段的视觉刺激一致。
        stimulus_phase = step.text_duration is None or elapsed < step.text_duration
        feedback_shown = (
            step.metadata.get("trial_kind") not in {"practice", "assessment"}
            and bool(self.current_context.get("nback_feedback_enabled"))
            and stimulus_phase
        )
        self._push_step_marker(
            str(step.metadata.get("response_event", "nback_response")),
            int(step.metadata.get("response_code", 459)),
            step,
            response_key="space",
            reaction_time_s=round(elapsed, 6),
            correct=correct,
            false_start=false_start,
            feedback_shown=feedback_shown,
        )
        if feedback_shown:
            feedback_text = "✓ 正确" if correct else "✕ 错误"
            feedback_color = "#14804a" if correct else "#b42318"
            self.cue_label.configure(
                text=feedback_text,
                font=(UI_FONT_FAMILY, self._cue_font_size(feedback_text, False), "bold"),
                foreground=feedback_color,
            )
        return "break"

    def _complete_manual_step(self) -> None:
        if not self.active or self.stopping or not 0 <= self.step_index < len(self.plan):
            return
        step = self.plan[self.step_index]
        if step.advance not in {"form", "operator"} or self.step_completion_started:
            return
        generation = self.step_generation
        step_index = self.step_index
        self.action_button.configure(state="disabled")
        responses: dict[str, object] = {}
        if step.advance == "form":
            collected = self._read_inline_form(step.fields)
            if collected is None:
                self.action_button.configure(state="normal")
                return
            if step.event == "nback_precheck_start" and not collected.get("ready_to_continue"):
                self.form_error.set("当前状态不适合继续 M2；请按 Esc 中止本模块，休息后使用新 Run 重新采集。")
                self.action_button.configure(state="normal")
                return
            if step.event == "readiness_context_start" and not collected.get("ready_to_test"):
                self.form_error.set("当前不适合继续筛查；请按 Esc 中止，必要时按现场安全或医疗流程处理。")
                self.action_button.configure(state="normal")
                return
            if step.event == "readiness_context_start":
                self.current_context.update(collected)
            responses = collected
        if step.block is not None and step.block in self.block_results:
            results = self.block_results[step.block]
            correct_count = sum(results)
            responses.update(
                {
                    "correct_count": correct_count,
                    "trial_count": len(results),
                    "accuracy": round(correct_count / len(results), 6) if results else None,
                }
            )
        self.action_button.pack_forget()
        self.task_frame.focus_set()
        self._complete_current_step(
            expected_generation=generation,
            expected_step_index=step_index,
            **responses,
        )

    def _complete_current_step(
        self,
        *,
        expected_generation: int | None = None,
        expected_step_index: int | None = None,
        **completion_data: object,
    ) -> None:
        if not self.active or self.stopping or not 0 <= self.step_index < len(self.plan):
            return
        if expected_generation is not None and expected_generation != self.step_generation:
            return
        if expected_step_index is not None and expected_step_index != self.step_index:
            return
        if self.step_completion_started:
            return
        generation = self.step_generation
        step_index = self.step_index
        self.step_completion_started = True
        step = self.plan[self.step_index]
        if step.response_key is not None:
            responded = self.current_response_time is not None
            reaction_time = (
                round(self.current_response_time - self.step_started, 6)
                if self.current_response_time is not None
                else None
            )
            if step.metadata.get("trial_kind") in {"practice", "assessment"}:
                should_respond = bool(step.metadata.get("should_respond"))
                trial_result = classify_sart_trial(
                    should_respond,
                    reaction_time,
                    false_start_threshold_s=float(step.metadata.get("false_start_threshold_s", 0.1)),
                )
                correct = bool(trial_result["correct"])
            else:
                is_target = bool(step.metadata.get("is_target"))
                correct = responded == is_target
                trial_result = {
                    "responded": responded,
                    "correct": correct,
                    "reaction_time_s": reaction_time,
                }
            self._push_step_marker(
                str(step.metadata.get("result_event", "nback_trial_result")),
                int(step.metadata.get("result_code", 460)),
                step,
                **trial_result,
            )
            if step.metadata.get("trial_kind") == "assessment":
                self.readiness_trials.append(
                    {
                        "trial": step.trial,
                        "stimulus": step.metadata.get("stimulus"),
                        "should_respond": bool(step.metadata.get("should_respond")),
                        **trial_result,
                    }
                )
            if step.block is not None:
                self.block_results.setdefault(step.block, []).append(correct)
        if step.completion_event is not None:
            self._push_step_marker(
                step.completion_event,
                step.completion_code,
                step,
                **completion_data,
            )
        if step.end_sound is not None:
            self._play_audio_cue(step.end_sound, step, "end")
        self.pending_advance_id = self.root.after_idle(
            lambda: self._advance_after_completion(generation, step_index)
        )

    def _advance_after_completion(self, generation: int, step_index: int) -> None:
        self.pending_advance_id = None
        if (
            not self.active
            or self.stopping
            or generation != self.step_generation
            or step_index != self.step_index
            or not self.step_completion_started
        ):
            return
        self._advance_step()

    def _tick_step(self, generation: int | None = None, step_index: int | None = None) -> None:
        generation = self.step_generation if generation is None else generation
        step_index = self.step_index if step_index is None else step_index
        if not self.active or self.stopping or self.step_index >= len(self.plan):
            return
        if generation != self.step_generation or step_index != self.step_index or self.step_completion_started:
            return
        self.tick_id = None
        step = self.plan[self.step_index]
        elapsed = time.monotonic() - self.step_started
        remaining = max(0.0, step.duration - elapsed)
        if step.text_duration is not None and elapsed >= step.text_duration and not self.step_text_replaced:
            replacement = step.text_after or ""
            self._display_visual(None)
            self.cue_label.configure(
                text=replacement,
                font=(UI_FONT_FAMILY, self._cue_font_size(replacement, False), "bold"),
                foreground=self.default_cue_foreground,
            )
            self.step_text_replaced = True
        self.countdown_label.configure(text=f"{remaining:0.1f} s")
        if (
            step.warning_sound is not None
            and step.warning_at is not None
            and remaining <= step.warning_at
            and not self.audio_warning_played
        ):
            self.audio_warning_played = True
            self._play_audio_cue(step.warning_sound, step, "warning")
        now = time.monotonic()
        if self.xdf_path is not None and now - self.last_file_poll >= 1.0:
            self.last_file_poll = now
            recorder = getattr(self, "_recorder_client", None)
            if isinstance(recorder, EmbeddedRecorderClient) and (recorder_errors := recorder.errors()):
                self._push_marker(
                    {
                        "code": 13,
                        "event": "recording_error",
                        "error": recorder_errors[0],
                        **self.current_context,
                        "app_version": APP_VERSION,
                        "unix_time": time.time(),
                    }
                )
                self.status.set(f"检测到内置录制错误：{recorder_errors[0]}")
                self._show_saving_state()
                self._stop_and_return(aborted=True)
                return
            try:
                self.xdf_current_size = self.xdf_path.stat().st_size
            except FileNotFoundError:
                self.xdf_current_size = 0
            self.progress_label.configure(
                text=f"步骤 {self.step_index + 1}/{len(self.plan)}  |  XDF {self.xdf_current_size / 1024:.1f} KB"
            )
        if remaining <= 0:
            self._complete_current_step(
                expected_generation=generation,
                expected_step_index=step_index,
            )
            return
        self.tick_id = self.root.after(50, lambda: self._tick_step(generation, step_index))

    def _push_marker(self, payload: dict) -> float:
        timestamp = local_clock()
        payload = {**payload, "lsl_timestamp": timestamp}
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.marker_outlet.push_sample([line], timestamp)
        if self.log_handle:
            self.log_handle.write(line + "\n")
            self.log_handle.flush()
        return timestamp

    def _finish_experiment(self) -> None:
        if not self.active:
            return
        if self.recording_mode.get() == RECORDING_MODE_MANUAL:
            self._show_task_action(
                "请停止手动录制",
                "在 LabRecorder 中点击 Stop，确认文件已保存后，再点击下方按钮。",
                "已停止，验证 XDF",
                self._confirm_manual_recording_stopped,
                allow_abort=False,
            )
            return
        self._show_saving_state()
        self.root.after(1000, lambda: self._stop_and_return(aborted=False))

    def _confirm_manual_recording_stopped(self) -> None:
        if not self.active or self.stopping:
            return
        self._show_saving_state()
        self.root.after(500, lambda: self._stop_and_return(aborted=False))

    def _show_saving_state(self) -> None:
        self._hide_inline_form()
        self._display_visual(None)
        self.action_button.pack_forget()
        self.secondary_button.pack_forget()
        self.abort_button.pack_forget()
        self.quality_frame.pack_forget()
        self.cue_label.configure(
            text="正在保存数据",
            font=(UI_FONT_FAMILY, 48, "bold"),
            foreground=self.default_cue_foreground,
        )
        self.detail_label.configure(text="正在关闭并验证 XDF，请勿关闭程序")
        self.countdown_label.configure(text="")

    def abort_experiment(self) -> None:
        if not self.active or self.stopping:
            return
        if not messagebox.askyesno("中止实验", "确认中止当前实验并停止录制？"):
            return
        self._push_marker(
            {
                "code": 12,
                "event": "experiment_abort",
                **self.current_context,
                "app_version": APP_VERSION,
                "unix_time": time.time(),
            }
        )
        if self.recording_mode.get() == RECORDING_MODE_MANUAL:
            self._show_task_action(
                "正在中止模块",
                "请先在 LabRecorder 中点击 Stop 保存当前数据，再确认继续。",
                "已停止，保存并返回",
                lambda: self._stop_and_return(aborted=True),
                allow_abort=False,
            )
            return
        self._stop_and_return(aborted=True)

    def _stop_and_return(self, aborted: bool) -> None:
        if self.stopping:
            return
        self.stopping = True
        self._cancel_step_callbacks()

        def stop() -> None:
            error: Exception | None = None
            final_size: int | None = None
            if self.recorder_started:
                try:
                    final_size = self._recorder_client.stop_recording(self.xdf_path)
                except Exception as caught:  # noqa: BLE001 - surfaced to the operator
                    error = caught
                finally:
                    if self.recorder_log_path is not None:
                        self._recorder_client.write_diagnostics(self.recorder_log_path)
            elif self.xdf_path is not None:
                try:
                    final_size = LabRecorderClient.wait_for_xdf(self.xdf_path, timeout=5.0)
                except Exception as caught:  # noqa: BLE001 - surfaced to the operator
                    error = caught
            self._post_to_ui(lambda: self._stopped(aborted, error, final_size))

        threading.Thread(target=stop, daemon=True).start()

    def _stopped(self, aborted: bool, error: Exception | None, final_size: int | None) -> None:
        self.stopping = False
        completed_task = self.current_task
        completed_title = PROTOCOL_BY_TASK[completed_task].title if completed_task else "当前模块"
        if error is not None:
            self.status.set("实验提示已结束，但 XDF 未通过保存验证")
        elif self.recording_mode.get() == RECORDING_MODE_MANUAL:
            self.status.set(f"{completed_title} 已结束，XDF 当前大小 {(final_size or 0) / 1024:.1f} KB")
        elif aborted:
            self.status.set(f"{completed_title} 已中止，XDF 已保存 {(final_size or 0) / 1024:.1f} KB")
        else:
            self.status.set(f"{completed_title} 完成，XDF 已验证并保存 {(final_size or 0) / 1024:.1f} KB")

        succeeded = error is None and not aborted
        if succeeded and completed_task in self.module_vars:
            self.module_vars[completed_task].set(False)
            self._update_estimate()
        self._close_current_files()
        self.active = False

        if error is not None:
            recovery = (
                "请检查录制诊断日志。本模块不会被标记为成功。"
                if self.recording_mode.get() == RECORDING_MODE_EMBEDDED
                else "请立即查看 LabRecorder，必要时手动点击 Stop。本模块不会被标记为成功。"
            )
            self._show_task_action(
                "XDF 未通过保存验证",
                f"{error}\n\n{recovery}",
                "返回首页检查",
                self._return_to_setup,
            )
            return
        if aborted:
            self._show_task_action(
                "模块已中止",
                f"{completed_title} 的已采数据已保存，重新采集时请使用新的 Run 编号。",
                "返回首页",
                self._return_to_setup,
            )
            return

        has_next = succeeded and self.module_index + 1 < len(self.module_queue)
        if completed_task == "m6_readiness" and self.readiness_result is not None:
            result = self.readiness_result
            if has_next:
                next_task = self.module_queue[self.module_index + 1]
                self.pending_next_task = next_task
                self._show_task_action(
                    str(result["label"]),
                    self._readiness_result_detail(result)
                    + f"\n\n下一个模块：{PROTOCOL_BY_TASK[next_task].title}",
                    "开始下一个模块",
                    self._continue_to_next_module,
                    secondary_text="暂不继续，返回首页",
                    secondary_command=self._return_to_setup,
                )
            else:
                self._show_task_action(
                    str(result["label"]),
                    self._readiness_result_detail(result),
                    "返回首页",
                    self._return_to_setup,
                )
            return
        if has_next:
            next_task = self.module_queue[self.module_index + 1]
            self.pending_next_task = next_task
            self._show_task_action(
                "模块已保存",
                f"{completed_title} 已完成。下一个模块：{PROTOCOL_BY_TASK[next_task].title}",
                "开始下一个模块",
                self._continue_to_next_module,
                secondary_text="暂不继续，返回首页",
                secondary_command=self._return_to_setup,
            )
            return
        self._show_task_action(
            "采集完成",
            "所有所选模块均已完成并保存。",
            "返回首页",
            self._return_to_setup,
        )

    def _continue_to_next_module(self) -> None:
        if self.pending_next_task is None:
            return
        self.module_index += 1
        self._begin_current_module()

    def _close_current_files(self) -> None:
        if self.log_handle:
            self.log_handle.close()
            self.log_handle = None
        self.event_log_path = None
        self.recorder_started = False
        self.xdf_path = None
        self.recorder_log_path = None
        self.current_response_time = None

    def _cancel_step_callbacks(self) -> None:
        self.step_generation += 1
        self.step_completion_started = True
        for attribute in ("tick_id", "pending_advance_id"):
            callback_id = getattr(self, attribute, None)
            if callback_id is not None:
                try:
                    self.root.after_cancel(callback_id)
                except Exception:  # noqa: BLE001 - callback may already be executing
                    pass
                setattr(self, attribute, None)

    def _return_to_setup(self) -> None:
        self._cancel_step_callbacks()
        self.active = False
        self.stopping = False
        self._close_current_files()
        self.action_button.pack_forget()
        self.secondary_button.pack_forget()
        self.abort_button.pack(side="right")
        self.quality_frame.pack_forget()
        self._hide_inline_form()
        self._display_visual(None)
        self.root.attributes("-fullscreen", False)
        self.task_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True)
        preset = ACQUISITION_BATCH_PRESETS.get(self.acquisition_batch.get())
        if preset is not None and tuple(self._selected_modules()) != preset[1]:
            self.acquisition_batch.set(CUSTOM_ACQUISITION_BATCH)
            self._update_acquisition_batch_detail()

    def on_close(self) -> None:
        if self.stopping:
            self.status.set("正在停止录制并验证文件，请稍候，暂时不能关闭。")
            return
        if self.active:
            self.abort_experiment()
            return
        if self.ui_action_poll_id is not None:
            self.root.after_cancel(self.ui_action_poll_id)
            self.ui_action_poll_id = None
        if self.task_signal_poll_id is not None:
            self.root.after_cancel(self.task_signal_poll_id)
            self.task_signal_poll_id = None
        self.task_signal_manager.stop()
        self.root.destroy()


def run_self_test() -> dict[str, object]:
    short_plan = build_deviceqc_plan(short=True)
    full_plan = build_deviceqc_plan(short=False)
    short_events = [step for step in short_plan if step.event]
    full_events = [step for step in full_plan if step.event]
    assert short_plan[0].event == "experiment_start"
    assert short_plan[-1].event == "experiment_end"
    assert sum(step.event == "head_left" for step in full_plan) == 5
    assert sum(step.event == "head_cancel" for step in full_plan) == 5
    assert build_xdf_filename("pilot01", "01", "deviceqc", "001") == (
        "sub-pilot01_ses-01_task-deviceqc_run-001.xdf"
    )
    validate_identifier("pilot_01", "test")
    try:
        validate_identifier("bad id", "test")
    except ValueError:
        pass
    else:
        raise AssertionError("Identifier validation accepted spaces")
    protocol_summary: dict[str, dict[str, float | int]] = {}
    for protocol in PROTOCOLS:
        plan = build_protocol_plan(protocol.task, short=True, seed=42)
        assert plan[0].event == "experiment_start"
        assert plan[-1].event == "experiment_end"
        protocol_summary[protocol.task] = {
            "steps": len(plan),
            "duration_s": round(sum(step.duration for step in plan), 1),
        }
    return {
        "app_version": APP_VERSION,
        "short_steps": len(short_plan),
        "short_markers": len(short_events),
        "short_duration_s": round(sum(step.duration for step in short_plan), 1),
        "full_steps": len(full_plan),
        "full_markers": len(full_events),
        "full_duration_s": round(sum(step.duration for step in full_plan), 1),
        "protocols": protocol_summary,
        "status": "ok",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--short", action="store_true", help="Preselect the short integration protocol")
    parser.add_argument("--monitor", action="store_true", help="Open only the BioMultiLite LSL live monitor")
    parser.add_argument("--self-test", action="store_true", help="Validate the protocol without opening the GUI")
    parser.add_argument(
        "--self-test-output",
        type=Path,
        help="Write self-test JSON to this file (used to verify windowed release builds)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        rendered = json.dumps(run_self_test(), ensure_ascii=False)
        if args.self_test_output is not None:
            args.self_test_output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return
    if args.monitor:
        from .monitor import run_live_monitor

        run_live_monitor()
        return
    root = Tk()
    BSenseExperimentApp(root, default_short=args.short)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
