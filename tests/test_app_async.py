import threading
import time
import unittest
from inspect import signature
from pathlib import Path
from queue import SimpleQueue

from bsense_experiment.app import (
    ACQUISITION_BATCH_PRESETS,
    BSenseExperimentApp,
    CUSTOM_ACQUISITION_BATCH,
    QUICK_READINESS_LABEL,
    THREE_BATCH_1_LABEL,
    THREE_BATCH_2_LABEL,
    THREE_BATCH_3_LABEL,
    TWO_BATCH_A_LABEL,
    TWO_BATCH_B_LABEL,
    eeg_clipped_channel_count,
    flat_channel_count,
    motion_activity_metrics,
)
from bsense_experiment.live import DataWindow, StreamDescriptor
from bsense_experiment.protocols import PROTOCOLS, Step


class FakeRoot:
    def __init__(self) -> None:
        self.after_threads: list[int] = []
        self.idle_callbacks: list[object] = []
        self.cancelled: list[str] = []
        self.exists = True

    def after(self, _milliseconds: int, _callback: object) -> str:
        self.after_threads.append(threading.get_ident())
        return "poll-1"

    def winfo_exists(self) -> bool:
        return self.exists

    def after_idle(self, callback: object) -> str:
        self.idle_callbacks.append(callback)
        return "idle-1"

    def after_cancel(self, callback_id: str) -> None:
        self.cancelled.append(callback_id)


class FakeLabel:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def configure(self, **options: object) -> None:
        self.options.update(options)


class FakeVariable:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self) -> object:
        return self.value

    def set(self, value: object) -> None:
        self.value = value


class AppAsyncTests(unittest.TestCase):
    def test_acquisition_batch_presets_repeat_baseline_and_keep_fatigue_late(self) -> None:
        expected = {
            QUICK_READINESS_LABEL: ("m6_readiness",),
            TWO_BATCH_A_LABEL: ("m0_baseline", "m1_mi", "m4a_intent", "m4b_target"),
            TWO_BATCH_B_LABEL: ("m0_baseline", "m2_nback", "m3a_safety", "m3b_fatigue", "m5_debrief"),
            THREE_BATCH_1_LABEL: ("m0_baseline", "m1_mi", "m4a_intent"),
            THREE_BATCH_2_LABEL: ("m0_baseline", "m2_nback", "m4b_target"),
            THREE_BATCH_3_LABEL: ("m0_baseline", "m3a_safety", "m3b_fatigue", "m5_debrief"),
        }
        self.assertEqual({label: preset[1] for label, preset in ACQUISITION_BATCH_PRESETS.items()}, expected)
        self.assertTrue(
            all(tasks[0] == "m0_baseline" for label, tasks in expected.items() if label != QUICK_READINESS_LABEL)
        )
        self.assertTrue(all("deviceqc" not in tasks for tasks in expected.values()))
        self.assertTrue(
            all(
                tasks[-1] in {"m4a_intent", "m4b_target", "m5_debrief"}
                for label, tasks in expected.items()
                if label != QUICK_READINESS_LABEL
            )
        )

    def test_applying_acquisition_batch_selects_modules_and_disables_short_mode(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.acquisition_batch = FakeVariable(TWO_BATCH_A_LABEL)
        app.acquisition_batch_detail = FakeVariable("")
        app.skip_m0 = FakeVariable(False)
        app.module_vars = {protocol.task: FakeVariable(False) for protocol in PROTOCOLS}
        app.short_protocol = FakeVariable(True)
        app.practice_ready = FakeVariable(True)
        estimates: list[bool] = []
        app._update_estimate = lambda: estimates.append(True)

        app._apply_acquisition_batch()

        selected = tuple(task for task, variable in app.module_vars.items() if variable.get())
        self.assertEqual(selected, ACQUISITION_BATCH_PRESETS[TWO_BATCH_A_LABEL][1])
        self.assertFalse(app.short_protocol.get())
        self.assertFalse(app.practice_ready.get())
        self.assertIn("48.7", app.acquisition_batch_detail.get())
        self.assertEqual(estimates, [True])

        app._module_selection_changed()
        self.assertEqual(app.acquisition_batch.get(), CUSTOM_ACQUISITION_BATCH)

    def test_skip_m0_removes_baseline_from_applied_batch(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.acquisition_batch = FakeVariable(TWO_BATCH_B_LABEL)
        app.acquisition_batch_detail = FakeVariable("")
        app.skip_m0 = FakeVariable(True)
        app.module_vars = {protocol.task: FakeVariable(False) for protocol in PROTOCOLS}
        app.short_protocol = FakeVariable(False)
        app.practice_ready = FakeVariable(False)
        app._update_estimate = lambda: None

        app._apply_acquisition_batch()

        selected = tuple(task for task, variable in app.module_vars.items() if variable.get())
        expected = tuple(
            task for task in ACQUISITION_BATCH_PRESETS[TWO_BATCH_B_LABEL][1] if task != "m0_baseline"
        )
        self.assertEqual(selected, expected)

        app.skip_m0.set(False)
        app._skip_m0_changed()
        selected = tuple(task for task, variable in app.module_vars.items() if variable.get())
        self.assertEqual(selected, ACQUISITION_BATCH_PRESETS[TWO_BATCH_B_LABEL][1])

    def test_short_protocol_is_opt_in_for_app_and_launchers(self) -> None:
        default_short = signature(BSenseExperimentApp.__init__).parameters["default_short"].default
        project_root = Path(__file__).resolve().parents[1]
        macos_launcher = (project_root / "macos" / "run.sh").read_text(encoding="utf-8")
        windows_launcher = (project_root / "windows" / "run.bat").read_text(encoding="utf-8")

        self.assertFalse(default_short)
        self.assertNotIn("bsense_experiment --short", macos_launcher)
        self.assertNotIn("bsense_experiment --short", windows_launcher)
        self.assertIn('"$@"', macos_launcher)
        self.assertIn("%*", windows_launcher)

    def test_worker_posts_ui_action_without_calling_tk(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.root = FakeRoot()
        app.ui_actions = SimpleQueue()
        app.ui_action_poll_id = None
        callback_threads: list[int] = []
        main_thread = threading.get_ident()

        worker = threading.Thread(target=lambda: app._post_to_ui(lambda: callback_threads.append(threading.get_ident())))
        worker.start()
        worker.join()

        self.assertEqual(app.root.after_threads, [])
        app._poll_ui_actions()
        self.assertEqual(callback_threads, [main_thread])
        self.assertEqual(app.root.after_threads, [main_thread])
        self.assertEqual(app.ui_action_poll_id, "poll-1")

    def test_flat_channel_count_only_flags_constant_finite_channels(self) -> None:
        descriptor = StreamDescriptor("eeg", "EEG", "EEG", 2, 25.0, ("Fp1", "Fp2"), "source")
        window = DataWindow(
            descriptor,
            tuple(index / 25.0 for index in range(5)),
            ((1.0, 1.0), (1.0, 2.0), (1.0, 3.0), (1.0, 4.0), (1.0, 5.0)),
            5,
            None,
        )
        self.assertEqual(flat_channel_count(window), 1)

    def test_eeg_clipping_flags_a_channel_near_the_bsense_rail(self) -> None:
        descriptor = StreamDescriptor("eeg", "EEG", "EEG", 2, 250.0, ("Fp1", "Fp2"), "source")
        samples = tuple(
            (-375000.0 if index < 32 else -374500.0 + index, float(index)) for index in range(40)
        )
        window = DataWindow(descriptor, tuple(index / 250.0 for index in range(40)), samples, 40, None)

        self.assertEqual(eeg_clipped_channel_count(window), 1)

    def test_motion_activity_metrics_marks_large_gyro_span_for_review(self) -> None:
        descriptor = StreamDescriptor(
            "motion",
            "Motion",
            "Motion",
            6,
            25.0,
            ("ax", "ay", "az", "gx", "gy", "gz"),
            "source",
        )
        samples = tuple((0.0, 0.0, 1.0, float(index), 0.0, 0.0) for index in range(8))
        window = DataWindow(descriptor, tuple(index / 25.0 for index in range(8)), samples, 8, None)

        warning, acceleration_span, gyroscope_span = motion_activity_metrics(window)

        self.assertTrue(warning)
        self.assertEqual(acceleration_span, 0.0)
        self.assertEqual(gyroscope_span, 7.0)

    def test_nback_feedback_marks_and_colors_a_false_alarm(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.active = True
        app.stopping = False
        app.step_index = 0
        app.plan = [Step("B", "", 2.0, response_key="space", metadata={"is_target": False})]
        app.current_response_time = None
        app.current_context = {"nback_feedback_enabled": True}
        app.step_started = time.monotonic()
        app.step_text_replaced = False
        app.cue_label = FakeLabel()
        marker_extras: dict[str, object] = {}

        def capture_marker(_event: str, _code: int, _step: Step, **extras: object) -> None:
            marker_extras.update(extras)

        app._push_step_marker = capture_marker
        result = app._on_response_key(None)

        self.assertEqual(app.cue_label.options["text"], "✕ 错误")
        self.assertFalse(marker_extras["correct"])
        self.assertTrue(marker_extras["feedback_shown"])
        self.assertFalse(app.step_text_replaced)
        self.assertEqual(result, "break")

    def test_late_nback_response_does_not_overwrite_fixation(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.active = True
        app.stopping = False
        app.step_index = 0
        app.plan = [
            Step(
                "+",
                "",
                2.0,
                response_key="space",
                text_duration=1.5,
                text_after="+",
                metadata={"is_target": False},
            )
        ]
        app.current_response_time = None
        app.current_context = {"nback_feedback_enabled": True}
        app.step_started = time.monotonic() - 1.7
        app.step_text_replaced = True
        app.cue_label = FakeLabel()
        app.cue_label.configure(text="+")
        marker_extras: dict[str, object] = {}

        def capture_marker(_event: str, _code: int, _step: Step, **extras: object) -> None:
            marker_extras.update(extras)

        app._push_step_marker = capture_marker
        result = app._on_response_key(None)

        self.assertEqual(result, "break")
        self.assertEqual(app.cue_label.options["text"], "+")
        self.assertFalse(marker_extras["feedback_shown"])

    def test_manual_completion_cannot_advance_a_timed_nback_step(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.active = True
        app.stopping = False
        app.step_index = 0
        app.step_generation = 1
        app.step_completion_started = False
        app.plan = [Step("B", "", 2.0, response_key="space")]
        completions: list[dict[str, object]] = []
        app._complete_current_step = lambda **values: completions.append(values)

        app._complete_manual_step()

        self.assertEqual(completions, [])

    def test_step_completion_is_idempotent(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.root = FakeRoot()
        app.active = True
        app.stopping = False
        app.step_index = 0
        app.step_generation = 7
        app.step_completion_started = False
        app.plan = [Step("完成", "", 0.0, completion_event="done", completion_code=99)]
        markers: list[str] = []
        app._push_step_marker = lambda event, _code, _step, **_values: markers.append(event)

        app._complete_current_step(expected_generation=7, expected_step_index=0)
        app._complete_current_step(expected_generation=7, expected_step_index=0)

        self.assertEqual(markers, ["done"])
        self.assertEqual(len(app.root.idle_callbacks), 1)

    def test_sart_completion_records_commission_without_using_nback_markers(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.root = FakeRoot()
        app.active = True
        app.stopping = False
        app.step_index = 0
        app.step_generation = 1
        app.step_completion_started = False
        app.step_started = time.monotonic() - 0.3
        app.current_response_time = time.monotonic()
        app.readiness_trials = []
        app.block_results = {}
        app.plan = [
            Step(
                "3",
                "",
                1.0,
                block="sart_assessment",
                trial=1,
                response_key="space",
                metadata={
                    "stimulus": "3",
                    "should_respond": False,
                    "trial_kind": "assessment",
                    "result_event": "sart_trial_result",
                    "result_code": 723,
                },
            )
        ]
        markers: list[tuple[str, dict[str, object]]] = []
        app._push_step_marker = (
            lambda event, _code, _step, **values: markers.append((event, values))
        )

        app._complete_current_step(expected_generation=1, expected_step_index=0)

        self.assertEqual(markers[0][0], "sart_trial_result")
        self.assertEqual(markers[0][1]["outcome"], "commission")
        self.assertEqual(app.readiness_trials[0]["outcome"], "commission")

    def test_readiness_quality_gate_and_public_result_hide_detailed_metrics(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.current_context = {
            "kss_score": 4,
            "sleep_duration_band": "7–8小时",
            "assessment_attempt": "首次",
        }
        app.readiness_trials = [
            {
                "should_respond": index % 9 != 0,
                "outcome": "hit" if index % 9 != 0 else "correct_rejection",
                "reaction_time_s": 0.4 if index % 9 != 0 else None,
            }
            for index in range(180)
        ]
        app.readiness_quality_samples = 100
        app.readiness_quality_bad_samples = 11
        app.readiness_quality_issues = {"eeg_flat"}

        result = app._create_readiness_assessment(180)
        detail = app._readiness_result_detail(result)

        self.assertEqual(result["status"], "unable")
        self.assertNotIn("正确率", detail)
        self.assertNotIn("反应时", detail)

    def test_stale_tick_cannot_touch_the_new_step(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.active = True
        app.stopping = False
        app.step_index = 0
        app.step_generation = 3
        app.step_completion_started = False
        app.tick_id = "new-step-timer"
        app.plan = [Step("+", "", 10.0)]

        app._tick_step(generation=2, step_index=0)

        self.assertEqual(app.tick_id, "new-step-timer")


if __name__ == "__main__":
    unittest.main()
