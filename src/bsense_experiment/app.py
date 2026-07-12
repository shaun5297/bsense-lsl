#!/usr/bin/env python3
"""Run BSense-R device-QC cues and record precise LSL markers on Windows."""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, messagebox, ttk

from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, cf_string, local_clock

from . import __version__

APP_VERSION = __version__
MARKER_STREAM_NAME = "BSense Experiment Markers"
MARKER_STREAM_TYPE = "Markers"
DEFAULT_RCS_HOST = "127.0.0.1"
DEFAULT_RCS_PORT = 22345
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class Step:
    text: str
    detail: str
    duration: float
    event: str | None = None
    code: int | None = None
    block: str | None = None
    trial: int | None = None


def build_deviceqc_plan(short: bool = False) -> list[Step]:
    rest_seconds = 10.0 if short else 60.0
    repetitions = 1 if short else 5
    prepare_seconds = 1.0 if short else 2.0
    cue_seconds = 2.0
    recovery_seconds = 2.0 if short else 3.0

    plan = [
        Step("实验即将开始", "保持坐姿，双脚平放，尽量放松", 2.0, "experiment_start", 10),
        Step("睁眼静息", "注视屏幕中央，保持头部不动", rest_seconds, "rest_open_start", 100),
        Step("睁眼静息结束", "继续保持不动", 0.5, "rest_open_end", 101),
        Step("闭眼静息", "轻轻闭眼，保持清醒和头部不动", rest_seconds, "rest_closed_start", 110),
        Step("闭眼静息结束", "请睁开眼睛", 1.0, "rest_closed_end", 111),
    ]

    actions = [
        ("blink", 120, "自然眨眼 1 次", "不要用力挤眼"),
        ("jaw_clench", 130, "轻咬后放松", "咬紧约 1 秒，然后完全放松"),
        ("head_left", 201, "缓慢左转头并回中", "只转到舒适位置，不要转动身体"),
        ("head_right", 202, "缓慢右转头并回中", "只转到舒适位置，不要转动身体"),
        ("head_nod", 203, "缓慢点头并回中", "完成一次点头后回到正中"),
        ("head_cancel", 204, "快速左右摇头并回中", "幅度适中，完成后回到正中"),
    ]
    for block_name, code, cue_text, cue_detail in actions:
        plan.append(
            Step(
                f"准备：{cue_text}",
                f"本组共 {repetitions} 次",
                1.0,
                f"block_start_{block_name}",
                20,
                block_name,
            )
        )
        for trial in range(1, repetitions + 1):
            plan.extend(
                [
                    Step(
                        "准备",
                        f"{cue_text}，第 {trial}/{repetitions} 次",
                        prepare_seconds,
                        block=block_name,
                        trial=trial,
                    ),
                    Step(
                        cue_text,
                        cue_detail,
                        cue_seconds,
                        block_name,
                        code,
                        block_name,
                        trial,
                    ),
                    Step(
                        "恢复正中并静止",
                        "放松，等待下一次提示",
                        recovery_seconds,
                        block=block_name,
                        trial=trial,
                    ),
                ]
            )
        plan.append(
            Step(
                f"{cue_text}组结束",
                "保持正中姿势",
                0.5,
                f"block_end_{block_name}",
                21,
                block_name,
            )
        )

    plan.extend(
        [
            Step("结束睁眼静息", "注视屏幕中央，保持头部不动", rest_seconds, "rest_open_final_start", 100),
            Step("结束静息完成", "继续保持不动", 0.5, "rest_open_final_end", 101),
            Step("实验完成", "请等待数据文件保存完成", 1.0, "experiment_end", 11),
        ]
    )
    return plan


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

    def command(self, command: str) -> str:
        self.connect()
        assert self.sock is not None
        self.sock.sendall((command + "\n").encode("utf-8"))
        response = b""
        while len(response) < 2:
            chunk = self.sock.recv(2 - len(response))
            if not chunk:
                raise ConnectionError(f"LabRecorder 在响应命令 {command!r} 前断开连接")
            response += chunk
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
            self.command("stop")
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
        self.root.geometry("920x640")
        self.root.minsize(820, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Escape>", lambda _event: self.abort_experiment())

        self.participant = StringVar(value="pilot01")
        self.session = StringVar(value="01")
        self.run = StringVar(value="001")
        self.task = StringVar(value="deviceqc")
        self.output_root = StringVar(value=r"C:\BCI\data\bsense")
        self.rcs_host = StringVar(value=DEFAULT_RCS_HOST)
        self.rcs_port = StringVar(value=str(DEFAULT_RCS_PORT))
        self.short_protocol = BooleanVar(value=default_short)
        self.auto_labrecorder = BooleanVar(value=True)
        self.status = StringVar(value="LSL Marker 流已发布，等待开始")

        self.marker_outlet = self._create_marker_outlet()
        self.active = False
        self.plan: list[Step] = []
        self.step_index = -1
        self.step_started = 0.0
        self.tick_id: str | None = None
        self.log_handle = None
        self.current_context: dict[str, str] = {}
        self.labrecorder_started = False
        self.xdf_path: Path | None = None
        self.xdf_initial_size = 0
        self.xdf_current_size = 0
        self.last_file_poll = 0.0
        self.recorder_log_path: Path | None = None

        self._build_setup_view()
        self._build_task_view()
        self.task_frame.pack_forget()

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
        self.setup_frame = ttk.Frame(self.root, padding=28)
        self.setup_frame.pack(fill="both", expand=True)

        ttk.Label(self.setup_frame, text="BSense-R 设备验证实验", font=("Microsoft YaHei UI", 22, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            self.setup_frame,
            text="自动发布精确 LSL Marker，并通过 RCS 控制官方 LabRecorder。",
            font=("Microsoft YaHei UI", 11),
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 24))

        fields = [
            ("被试编号", self.participant),
            ("会话编号", self.session),
            ("Run 编号", self.run),
            ("任务名称", self.task),
            ("数据目录", self.output_root),
            ("RCS 主机", self.rcs_host),
            ("RCS 端口", self.rcs_port),
        ]
        for row, (label, variable) in enumerate(fields, start=2):
            ttk.Label(self.setup_frame, text=label).grid(row=row, column=0, sticky="w", pady=7)
            entry = ttk.Entry(self.setup_frame, textvariable=variable)
            entry.grid(row=row, column=1, columnspan=3, sticky="ew", padx=(14, 0), pady=7)

        ttk.Checkbutton(
            self.setup_frame,
            text="短流程（约 1 分钟，用于首次联调）",
            variable=self.short_protocol,
        ).grid(row=9, column=0, columnspan=4, sticky="w", pady=(18, 6))
        ttk.Checkbutton(
            self.setup_frame,
            text="自动控制 LabRecorder（需勾选 Enable RCS，端口 22345）",
            variable=self.auto_labrecorder,
        ).grid(row=10, column=0, columnspan=4, sticky="w", pady=6)

        ttk.Separator(self.setup_frame).grid(row=11, column=0, columnspan=4, sticky="ew", pady=20)
        ttk.Label(self.setup_frame, textvariable=self.status).grid(row=12, column=0, columnspan=4, sticky="w")

        ttk.Button(self.setup_frame, text="发送测试 Marker", command=self.send_test_marker).grid(
            row=13, column=0, sticky="w", pady=(22, 0)
        )
        ttk.Button(self.setup_frame, text="开始实验", command=self.start_experiment).grid(
            row=13, column=3, sticky="e", pady=(22, 0)
        )

        self.setup_frame.columnconfigure(1, weight=1)
        self.setup_frame.columnconfigure(2, weight=1)

    def _build_task_view(self) -> None:
        self.task_frame = ttk.Frame(self.root, padding=32)
        self.progress_label = ttk.Label(self.task_frame, text="", font=("Microsoft YaHei UI", 12))
        self.progress_label.pack(anchor="nw")
        ttk.Separator(self.task_frame).pack(fill="x", pady=18)

        self.cue_label = ttk.Label(
            self.task_frame,
            text="",
            anchor="center",
            justify="center",
            font=("Microsoft YaHei UI", 34, "bold"),
        )
        self.cue_label.pack(fill="both", expand=True)
        self.detail_label = ttk.Label(
            self.task_frame,
            text="",
            anchor="center",
            justify="center",
            font=("Microsoft YaHei UI", 16),
        )
        self.detail_label.pack(fill="x", pady=12)
        self.countdown_label = ttk.Label(
            self.task_frame,
            text="",
            anchor="center",
            font=("Microsoft YaHei UI", 26),
        )
        self.countdown_label.pack(fill="x", pady=12)
        ttk.Button(self.task_frame, text="中止实验 (Esc)", command=self.abort_experiment).pack(pady=(18, 0))

    def _collect_context(self) -> tuple[dict[str, str], Path, str]:
        participant = validate_identifier(self.participant.get(), "被试编号")
        session = validate_identifier(self.session.get(), "会话编号")
        run = validate_identifier(self.run.get(), "Run 编号")
        task = validate_identifier(self.task.get(), "任务名称")
        output_root = Path(self.output_root.get().strip())
        if not str(output_root):
            raise ValueError("数据目录不能为空")
        filename = build_xdf_filename(participant, session, task, run)
        return (
            {"participant": participant, "session": session, "run": run, "task": task},
            output_root,
            filename,
        )

    def send_test_marker(self) -> None:
        try:
            context, _, _ = self._collect_context()
        except ValueError as error:
            messagebox.showerror("参数错误", str(error))
            return
        payload = {
            "code": 1,
            "event": "marker_test",
            **context,
            "app_version": APP_VERSION,
            "unix_time": time.time(),
        }
        timestamp = self._push_marker(payload)
        self.status.set(f"已发送 marker_test，LSL 时间戳 {timestamp:.6f}")

    def start_experiment(self) -> None:
        if self.active:
            return
        try:
            context, output_root, filename = self._collect_context()
            port = int(self.rcs_port.get())
            if not 1 <= port <= 65535:
                raise ValueError("RCS 端口范围应为 1-65535")
        except (ValueError, OSError) as error:
            messagebox.showerror("参数错误", str(error))
            return

        if not messagebox.askokcancel(
            "开始前确认",
            "请确认：\n\n"
            "1. 被试保持坐姿并有操作员在场\n"
            "2. BioMultiLite 已连接，7 类 LSL 流已启动\n"
            "3. LabRecorder 已打开并启用 RCS 22345\n"
            "4. 当前不需要点击 BioMultiLite 本地 REC\n\n"
            f"目标文件：{filename}",
        ):
            return

        output_root.mkdir(parents=True, exist_ok=True)
        log_dir = output_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / filename.replace(".xdf", "_events.jsonl")
        recorder_log_path = log_dir / filename.replace(".xdf", "_recorder.jsonl")
        target_path = output_root.resolve() / filename
        existing = [path for path in (target_path, log_path, recorder_log_path) if path.exists()]
        if existing:
            messagebox.showerror(
                "目标文件已存在",
                "请更换被试或 Run 编号，程序不会覆盖已有数据：\n\n" + "\n".join(str(path) for path in existing),
            )
            return
        self.log_handle = log_path.open("w", encoding="utf-8")
        self.recorder_log_path = recorder_log_path
        self.xdf_path = target_path
        self.current_context = context
        self.plan = build_deviceqc_plan(self.short_protocol.get())
        self.step_index = -1
        self.active = True
        self.labrecorder_started = False
        self.xdf_initial_size = 0
        self.xdf_current_size = 0
        self.last_file_poll = 0.0

        self.setup_frame.pack_forget()
        self.task_frame.pack(fill="both", expand=True)
        self.root.attributes("-fullscreen", True)
        self.cue_label.configure(text="正在准备录制")
        self.detail_label.configure(text="请观察 LabRecorder 是否开始计时且文件大小增长")
        self.countdown_label.configure(text="")
        self.progress_label.configure(text=f"输出文件：{filename}")

        if self.auto_labrecorder.get():
            client = LabRecorderClient(self.rcs_host.get().strip(), port)

            def prepare() -> None:
                try:
                    xdf_path, initial_size = client.start_recording(output_root, filename)
                except Exception as error:  # noqa: BLE001 - surfaced to the operator
                    if self.recorder_log_path is not None:
                        client.write_diagnostics(self.recorder_log_path)
                    self.root.after(0, lambda error=error: self._prepare_failed(error))
                    return
                if self.recorder_log_path is not None:
                    client.write_diagnostics(self.recorder_log_path)
                self.root.after(0, lambda: self._recording_ready(client, xdf_path, initial_size))

            threading.Thread(target=prepare, daemon=True).start()
        else:
            self.root.after(500, self._manual_recording_ready)

    def _prepare_failed(self, error: Exception) -> None:
        if not self.active:
            return
        self.status.set(f"无法控制 LabRecorder：{error}")
        messagebox.showerror(
            "LabRecorder 连接失败",
            f"{error}\n\n请确认 Enable RCS 已勾选、端口为 22345，并且 LabRecorder 未在录制。",
        )
        self._return_to_setup()

    def _recording_ready(self, client: LabRecorderClient, xdf_path: Path, initial_size: int) -> None:
        if not self.active:
            try:
                client.stop_recording(xdf_path)
            except OSError:
                pass
            return
        self.labrecorder_started = True
        self._labrecorder_client = client
        self.xdf_path = xdf_path
        self.xdf_initial_size = initial_size
        self.xdf_current_size = initial_size
        self.cue_label.configure(text="录制已启动")
        self.detail_label.configure(text=f"已验证 XDF：{initial_size / 1024:.1f} KB，实验将在 2 秒后开始")
        self.root.after(2000, self._advance_step)

    def _manual_recording_ready(self) -> None:
        if not self.active:
            return
        ready = messagebox.askokcancel("手动录制", "请在 LabRecorder 中点击 Start。确认已经开始计时后继续。")
        if not ready:
            self.abort_experiment()
            return

        def verify_manual() -> None:
            try:
                assert self.xdf_path is not None
                initial_size = LabRecorderClient.wait_for_xdf(self.xdf_path)
            except Exception as error:  # noqa: BLE001 - surfaced to the operator
                self.root.after(0, lambda error=error: self._prepare_failed(error))
                return
            self.root.after(0, lambda: self._manual_xdf_ready(initial_size))

        threading.Thread(target=verify_manual, daemon=True).start()

    def _manual_xdf_ready(self, initial_size: int) -> None:
        if not self.active:
            return
        self.xdf_initial_size = initial_size
        self.xdf_current_size = initial_size
        self.cue_label.configure(text="录制已启动")
        self.detail_label.configure(text=f"已验证 XDF：{initial_size / 1024:.1f} KB，实验将在 2 秒后开始")
        self.root.after(2000, self._advance_step)

    def _advance_step(self) -> None:
        if not self.active:
            return
        self.step_index += 1
        if self.step_index >= len(self.plan):
            self._finish_experiment()
            return

        step = self.plan[self.step_index]
        self.step_started = time.monotonic()
        self.cue_label.configure(text=step.text)
        self.detail_label.configure(text=step.detail)
        self.progress_label.configure(text=f"步骤 {self.step_index + 1}/{len(self.plan)}")
        if step.event is not None:
            payload = {
                "code": step.code,
                "event": step.event,
                "block": step.block,
                "trial": step.trial,
                **self.current_context,
                "app_version": APP_VERSION,
                "unix_time": time.time(),
            }
            self._push_marker(payload)
        self._tick_step()

    def _tick_step(self) -> None:
        if not self.active or self.step_index >= len(self.plan):
            return
        step = self.plan[self.step_index]
        remaining = max(0.0, step.duration - (time.monotonic() - self.step_started))
        self.countdown_label.configure(text=f"{remaining:0.1f} s")
        now = time.monotonic()
        if self.xdf_path is not None and now - self.last_file_poll >= 1.0:
            self.last_file_poll = now
            try:
                self.xdf_current_size = self.xdf_path.stat().st_size
            except FileNotFoundError:
                self.xdf_current_size = 0
            self.progress_label.configure(
                text=f"步骤 {self.step_index + 1}/{len(self.plan)}  |  XDF {self.xdf_current_size / 1024:.1f} KB"
            )
        if remaining <= 0:
            self._advance_step()
            return
        self.tick_id = self.root.after(100, self._tick_step)

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
        self.cue_label.configure(text="正在保存数据")
        self.detail_label.configure(text="请勿关闭 LabRecorder")
        self.countdown_label.configure(text="")
        self.root.after(1000, lambda: self._stop_and_return(aborted=False))

    def abort_experiment(self) -> None:
        if not self.active:
            return
        if not messagebox.askyesno("中止实验", "确认中止当前实验并停止 LabRecorder？"):
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
        self._stop_and_return(aborted=True)

    def _stop_and_return(self, aborted: bool) -> None:
        if self.tick_id is not None:
            self.root.after_cancel(self.tick_id)
            self.tick_id = None

        def stop() -> None:
            error: Exception | None = None
            final_size: int | None = None
            if self.labrecorder_started:
                try:
                    final_size = self._labrecorder_client.stop_recording(self.xdf_path)
                except Exception as caught:  # noqa: BLE001 - surfaced to the operator
                    error = caught
                finally:
                    if self.recorder_log_path is not None:
                        self._labrecorder_client.write_diagnostics(self.recorder_log_path)
            elif self.xdf_path is not None:
                try:
                    final_size = LabRecorderClient.wait_for_xdf(self.xdf_path, timeout=5.0)
                except Exception as caught:  # noqa: BLE001 - surfaced to the operator
                    error = caught
            self.root.after(0, lambda: self._stopped(aborted, error, final_size))

        threading.Thread(target=stop, daemon=True).start()

    def _stopped(self, aborted: bool, error: Exception | None, final_size: int | None) -> None:
        if error is not None:
            messagebox.showwarning(
                "XDF 未验证",
                f"{error}\n\n请立即查看 LabRecorder，必要时手动点击 Stop。程序不会把本次任务标记为成功。",
            )
            self.status.set("实验提示已结束，但 XDF 未通过保存验证")
        elif not self.auto_labrecorder.get():
            messagebox.showinfo("停止录制", "请现在在 LabRecorder 中点击 Stop 保存 XDF。")
            self.status.set(f"手动模式已结束，XDF 当前大小 {(final_size or 0) / 1024:.1f} KB")
        elif aborted:
            self.status.set(f"实验已中止，XDF 已保存 {(final_size or 0) / 1024:.1f} KB")
        else:
            self.status.set(f"实验完成，XDF 已验证并保存 {(final_size or 0) / 1024:.1f} KB")
        self._return_to_setup()

    def _return_to_setup(self) -> None:
        self.active = False
        self.labrecorder_started = False
        if self.log_handle:
            self.log_handle.close()
            self.log_handle = None
        self.xdf_path = None
        self.recorder_log_path = None
        self.root.attributes("-fullscreen", False)
        self.task_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True)

    def on_close(self) -> None:
        if self.active:
            self.abort_experiment()
            return
        self.root.destroy()


def run_self_test() -> None:
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
    print(
        json.dumps(
            {
                "app_version": APP_VERSION,
                "short_steps": len(short_plan),
                "short_markers": len(short_events),
                "short_duration_s": round(sum(step.duration for step in short_plan), 1),
                "full_steps": len(full_plan),
                "full_markers": len(full_events),
                "full_duration_s": round(sum(step.duration for step in full_plan), 1),
                "status": "ok",
            },
            ensure_ascii=False,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--short", action="store_true", help="Preselect the short integration protocol")
    parser.add_argument("--self-test", action="store_true", help="Validate the protocol without opening the GUI")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        run_self_test()
        return
    root = Tk()
    BSenseExperimentApp(root, default_short=args.short)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
