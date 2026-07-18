import unittest

from bsense_experiment.app import (
    build_deviceqc_plan,
    build_xdf_filename,
    validate_identifier,
)
from bsense_experiment.protocols import PROTOCOLS, build_protocol_plan


class ProtocolTests(unittest.TestCase):
    def test_short_protocol(self) -> None:
        plan = build_deviceqc_plan(short=True)
        markers = [step for step in plan if step.event]
        self.assertEqual(len(plan), 38)
        self.assertEqual(len(markers), 26)
        self.assertEqual(sum(step.duration for step in plan), 74.0)
        self.assertEqual(plan[0].event, "experiment_start")
        self.assertEqual(plan[-1].event, "experiment_end")

    def test_full_protocol_has_five_trials_per_action(self) -> None:
        plan = build_deviceqc_plan(short=False)
        for event in ("blink", "jaw_clench", "head_left", "head_right", "head_nod", "head_cancel"):
            self.assertEqual(sum(step.event == event for step in plan), 5)

    def test_filename_is_normalized(self) -> None:
        self.assertEqual(
            build_xdf_filename("Pilot01", "01", "DeviceQC", "001"),
            "sub-pilot01_ses-01_task-deviceqc_run-001.xdf",
        )

    def test_identifier_rejects_spaces(self) -> None:
        with self.assertRaises(ValueError):
            validate_identifier("bad id", "test")

    def test_every_module_has_experiment_boundaries(self) -> None:
        for protocol in PROTOCOLS:
            with self.subTest(task=protocol.task):
                plan = build_protocol_plan(protocol.task, short=True, seed=42)
                self.assertEqual(plan[0].event, "experiment_start")
                self.assertEqual(plan[-1].event, "experiment_end")

    def test_m1_is_balanced_and_reproducible(self) -> None:
        first = build_protocol_plan("m1_mi", seed=42)
        second = build_protocol_plan("m1_mi", seed=42)
        third = build_protocol_plan("m1_mi", seed=43)
        first_conditions = [step.event for step in first if step.event in {"mi_left", "mi_right", "mi_idle"}]
        second_conditions = [step.event for step in second if step.event in {"mi_left", "mi_right", "mi_idle"}]
        third_conditions = [step.event for step in third if step.event in {"mi_left", "mi_right", "mi_idle"}]
        self.assertEqual(first_conditions, second_conditions)
        self.assertNotEqual(first_conditions, third_conditions)
        for condition in ("mi_left", "mi_right", "mi_idle"):
            self.assertEqual(first_conditions.count(condition), 40)
        for run_number in range(1, 5):
            run_conditions = [
                step.event
                for step in first
                if step.event in {"mi_left", "mi_right", "mi_idle"}
                and step.metadata["run_in_task"] == run_number
            ]
            for condition in ("mi_left", "mi_right", "mi_idle"):
                self.assertEqual(run_conditions.count(condition), 10)
            self.assertFalse(
                any(
                    run_conditions[index - 2] == run_conditions[index - 1] == run_conditions[index]
                    for index in range(2, len(run_conditions))
                )
            )
        self.assertEqual(sum(step.event == "mi_cue" for step in first), 120)
        self.assertEqual(sum(step.event == "mi_trial_end" for step in first), 120)
        run_ratings = [step for step in first if step.event == "mi_run_rating_start"]
        self.assertEqual(len(run_ratings), 4)
        self.assertTrue(all(step.advance == "form" for step in run_ratings))
        self.assertTrue(all(step.metadata["rating_scope"] == "run" for step in run_ratings))

    def test_nback_stimuli_are_response_aware(self) -> None:
        plan = build_protocol_plan("m2_nback", short=True, seed=42)
        stimuli = [step for step in plan if step.event == "nback_stimulus"]
        self.assertEqual(len(stimuli), 24)
        self.assertTrue(all(step.response_key == "space" for step in stimuli))
        self.assertEqual({step.metadata["level"] for step in stimuli}, {0, 1, 2})
        self.assertTrue(all("is_target" in step.metadata for step in stimuli))
        self.assertTrue(all("position_in_block" in step.metadata for step in stimuli))
        for level in (0, 1, 2):
            level_stimuli = [step for step in stimuli if step.metadata["level"] == level]
            self.assertEqual(sum(bool(step.metadata["is_target"]) for step in level_stimuli), 2)
        self.assertEqual(sum(step.event == "nback_task_end" for step in plan), 3)
        self.assertEqual(sum(step.event == "block_rest_end" for step in plan), 3)

    def test_nback_supports_counterbalanced_level_order(self) -> None:
        plan = build_protocol_plan("m2_nback", short=True, seed=1, nback_order="counterbalanced")
        block_levels = [step.metadata["level"] for step in plan if step.event == "block_start"]
        self.assertEqual(block_levels, [1, 2, 0])
        self.assertTrue(
            all(step.metadata["nback_order"] == "counterbalanced" for step in plan if step.event == "block_start")
        )

    def test_m0_contains_operator_gate_and_questionnaire(self) -> None:
        plan = build_protocol_plan("m0_baseline", short=True)
        self.assertTrue(any(step.advance == "operator" for step in plan))
        questionnaire = next(step for step in plan if step.event == "baseline_questionnaire_start")
        self.assertEqual(questionnaire.advance, "form")
        self.assertEqual(
            {field.key for field in questionnaire.fields},
            {"fatigue", "sleep_quality", "neuroactive_medication"},
        )
        closed_rest = next(step for step in plan if step.event == "rest_closed_start")
        self.assertEqual(closed_rest.warning_sound, "ending_soon")
        self.assertEqual(closed_rest.end_sound, "open_eyes")
        settle = next(step for step in plan if step.event == "baseline_settle_start")
        self.assertIn("自然呼吸", settle.detail)
        self.assertIn("不要刻意深呼吸", settle.detail)

    def test_m4b_marks_selected_target(self) -> None:
        plan = build_protocol_plan("m4b_target", short=True, seed=42, target_object="手机")
        highlights = [step for step in plan if step.event == "target_highlight"]
        selected = [step for step in highlights if step.metadata["is_target"]]
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(step.metadata["object"] == "手机" for step in selected))
        self.assertTrue(all(step.visual in {"水杯", "药瓶", "手机"} for step in highlights))
        self.assertTrue(all("运动想象" not in step.detail for step in highlights))
        self.assertTrue(all(step.metadata["fnirs_analysis_scope"] == "block_level_only" for step in highlights))
        rating = next(step for step in plan if step.event == "target_attention_rating_start")
        self.assertEqual(rating.advance, "form")

    def test_m4a_balances_objects_within_each_condition(self) -> None:
        plan = build_protocol_plan("m4a_intent", seed=42)
        cues = [step for step in plan if step.event == "intent_cue"]
        for has_intent in (True, False):
            condition = [step for step in cues if step.metadata["has_intent"] is has_intent]
            counts = [sum(step.metadata["object"] == object_name for step in condition) for object_name in ("水杯", "药瓶", "手机")]
            self.assertEqual(len(condition), 40)
            self.assertLessEqual(max(counts) - min(counts), 1)
            self.assertTrue(all(step.metadata["paradigm"] == "externally_cued_intent" for step in condition))
        self.assertEqual(sum(step.event == "intent_present" for step in plan), 40)
        self.assertEqual(sum(step.event == "intent_absent" for step in plan), 40)
        self.assertEqual(sum(step.event == "intent_trial_end" for step in plan), 80)
        self.assertTrue(any(step.event == "intent_rating_start" for step in plan))

    def test_m3a_marks_expected_artifacts_without_claiming_contamination(self) -> None:
        plan = build_protocol_plan("m3a_safety", short=True)
        action = next(step for step in plan if step.event == "motion_nod")
        self.assertEqual(action.metadata["artifact_expectation"], "motion_expected")
        self.assertEqual(action.metadata["quality_status"], "requires_offline_review")
        self.assertNotIn("eeg_contaminated", action.metadata)
        self.assertNotIn("fnirs_contaminated", action.metadata)

    def test_m3b_uses_kss_and_explicit_segment_boundaries(self) -> None:
        plan = build_protocol_plan("m3b_fatigue", seed=42)
        ratings = [step for step in plan if step.event == "fatigue_rating_start"]
        self.assertEqual(len(ratings), 5)
        self.assertTrue(all({field.key for field in rating.fields} == {"kss_score", "mental_fatigue_score"} for rating in ratings))
        self.assertTrue(all(rating.fields[0].maximum == 9 for rating in ratings))
        self.assertEqual(sum(step.event == "fatigue_segment_start" for step in plan), 5)
        self.assertEqual(sum(step.event == "fatigue_segment_end" for step in plan), 5)
        self.assertEqual(sum(step.event == "fatigue_recovery_start" for step in plan), 1)
        stimuli = [step for step in plan if step.event == "nback_stimulus"]
        self.assertEqual({step.metadata["segment"] for step in stimuli}, {1, 2, 3, 4, 5})
        self.assertEqual({step.metadata["position_in_block"] for step in stimuli}, set(range(1, 61)))
        for segment in range(1, 6):
            segment_stimuli = [step for step in stimuli if step.metadata["segment"] == segment]
            self.assertEqual(sum(bool(step.metadata["is_target"]) for step in segment_stimuli), 15)
            self.assertTrue(all(step.metadata["sequence_reset"] for step in segment_stimuli))

    def test_m5_contains_structured_debrief(self) -> None:
        plan = build_protocol_plan("m5_debrief")
        debrief = next(step for step in plan if step.event == "debrief_start")
        self.assertEqual(debrief.advance, "form")
        self.assertEqual(
            {field.key for field in debrief.fields},
            {
                "kss_score",
                "mi_difficulty",
                "easiest_task",
                "hardest_task",
                "device_comfort",
                "headache",
                "dizziness_or_nausea",
                "skin_or_device_discomfort",
            },
        )


if __name__ == "__main__":
    unittest.main()
