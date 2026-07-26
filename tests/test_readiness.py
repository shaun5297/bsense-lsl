import unittest

from bsense_experiment.readiness import (
    assess_readiness,
    classify_sart_trial,
    normalize_readiness_context,
    sleep_duration_band,
    summarize_sart_trials,
)


def completed_trials() -> list[dict[str, object]]:
    return [
        {
            "should_respond": index % 9 != 0,
            "outcome": "hit" if index % 9 != 0 else "correct_rejection",
            "reaction_time_s": 0.35 + (index % 5) * 0.01 if index % 9 != 0 else None,
        }
        for index in range(180)
    ]


class ReadinessRuleTests(unittest.TestCase):
    def test_exact_sleep_and_parent_run_derive_rule_context(self) -> None:
        first = normalize_readiness_context(
            {
                "sleep_duration_hours": 7.5,
                "last_sleep_onset_time": "23:30",
                "last_wake_time": "07:00",
                "continuous_awake_hours": 2.0,
                "caffeine_mg_last_8h": 0.0,
                "last_caffeine_time": None,
                "parent_run_id": None,
                "rest_duration_minutes": None,
            },
            current_run_id="002",
        )
        self.assertEqual(first["sleep_duration_band"], "7–8小时")
        self.assertEqual(first["assessment_attempt"], "首次")

        retest = normalize_readiness_context(
            {
                **first,
                "sleep_duration_hours": 5.5,
                "caffeine_mg_last_8h": 100.0,
                "last_caffeine_time": "08:15",
                "parent_run_id": "001",
                "rest_duration_minutes": 12.0,
            },
            current_run_id="002",
        )
        self.assertEqual(retest["sleep_duration_band"], "5–6小时")
        self.assertEqual(retest["assessment_attempt"], "复测")
        self.assertEqual(retest["parent_run_id"], "001")

    def test_readiness_context_rejects_invalid_linkage_and_times(self) -> None:
        base = {
            "sleep_duration_hours": 7.0,
            "last_sleep_onset_time": "23:30",
            "last_wake_time": "07:00",
            "continuous_awake_hours": 2.0,
            "caffeine_mg_last_8h": 0.0,
            "last_caffeine_time": None,
            "parent_run_id": None,
            "rest_duration_minutes": None,
        }
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            normalize_readiness_context(
                {**base, "last_wake_time": "7点"},
                current_run_id="002",
            )
        with self.assertRaisesRegex(ValueError, "休息分钟"):
            normalize_readiness_context(
                {**base, "parent_run_id": "001"},
                current_run_id="002",
            )
        with self.assertRaisesRegex(ValueError, "不能与当前 Run 相同"):
            normalize_readiness_context(
                {
                    **base,
                    "parent_run_id": "002",
                    "rest_duration_minutes": 10.0,
                },
                current_run_id="002",
            )

    def test_sleep_duration_band_boundaries(self) -> None:
        self.assertEqual(sleep_duration_band(4.99), "少于5小时")
        self.assertEqual(sleep_duration_band(5.0), "5–6小时")
        self.assertEqual(sleep_duration_band(6.0), "6–7小时")
        self.assertEqual(sleep_duration_band(7.0), "7–8小时")
        self.assertEqual(sleep_duration_band(8.0), "8小时及以上")

    def test_sart_trial_classification_separates_false_starts_and_error_types(self) -> None:
        self.assertEqual(classify_sart_trial(True, 0.05)["outcome"], "false_start")
        self.assertEqual(classify_sart_trial(True, None)["outcome"], "omission")
        self.assertEqual(classify_sart_trial(False, 0.3)["outcome"], "commission")
        self.assertEqual(classify_sart_trial(False, None)["outcome"], "correct_rejection")
        self.assertEqual(classify_sart_trial(True, 0.3)["outcome"], "hit")

    def test_summary_does_not_treat_missing_responses_as_zero_latency(self) -> None:
        metrics = summarize_sart_trials(
            [
                {"should_respond": True, "outcome": "hit", "reaction_time_s": 0.4},
                {"should_respond": True, "outcome": "omission", "reaction_time_s": None},
                {"should_respond": False, "outcome": "correct_rejection", "reaction_time_s": None},
            ]
        )
        self.assertEqual(metrics["median_reaction_time_s"], 0.4)
        self.assertEqual(metrics["omission_rate"], 0.5)
        self.assertAlmostEqual(float(metrics["accuracy"]), 2 / 3, places=6)

    def test_assessment_exposes_all_four_states(self) -> None:
        normal_context = {
            "kss_score": 4,
            "sleep_duration_band": "7–8小时",
            "assessment_attempt": "首次",
            "shift_type": "日班",
        }
        normal = assess_readiness(
            normal_context,
            completed_trials(),
            expected_trials=180,
            signal_quality_ok=True,
        )
        self.assertEqual(normal["status"], "normal")
        self.assertFalse(normal["validated_for_employment_decisions"])

        retest = assess_readiness(
            {**normal_context, "kss_score": 8},
            completed_trials(),
            expected_trials=180,
            signal_quality_ok=True,
        )
        self.assertEqual(retest["status"], "retest")

        rest = assess_readiness(
            {**normal_context, "kss_score": 8, "assessment_attempt": "复测"},
            completed_trials(),
            expected_trials=180,
            signal_quality_ok=True,
        )
        self.assertEqual(rest["status"], "rest")

        unable = assess_readiness(
            normal_context,
            completed_trials(),
            expected_trials=180,
            signal_quality_ok=False,
            signal_quality_issues=("eeg_flat",),
        )
        self.assertEqual(unable["status"], "unable")
        self.assertIn("signal_quality_gate_failed", unable["reason_codes"])

    def test_first_attempt_never_escalates_directly_to_rest(self) -> None:
        risky_trials = [
            {
                "should_respond": True,
                "outcome": "omission",
                "reaction_time_s": None,
            }
            for _ in range(180)
        ]
        result = assess_readiness(
            {
                "kss_score": 9,
                "sleep_duration_band": "少于5小时",
                "assessment_attempt": "首次",
                "shift_type": "夜班",
            },
            risky_trials,
            expected_trials=180,
            signal_quality_ok=True,
        )
        self.assertEqual(result["status"], "retest")

    def test_no_go_false_start_counts_as_commission_and_false_start(self) -> None:
        trial = classify_sart_trial(False, 0.05)
        self.assertEqual(trial["outcome"], "commission")
        self.assertTrue(trial["false_start"])
        metrics = summarize_sart_trials(
            [
                {"should_respond": False, **trial},
                {"should_respond": False, "outcome": "correct_rejection", "reaction_time_s": None},
            ]
        )
        self.assertEqual(metrics["commission_count"], 1)
        self.assertEqual(metrics["commission_rate"], 0.5)
        self.assertEqual(metrics["false_start_count"], 1)
        self.assertEqual(metrics["false_start_rate"], 0.5)

    def test_false_start_boundary_is_strictly_below_100ms(self) -> None:
        self.assertEqual(classify_sart_trial(True, 0.1)["outcome"], "hit")
        self.assertEqual(classify_sart_trial(True, 0.0999)["outcome"], "false_start")

    def test_assessment_threshold_boundaries(self) -> None:
        context = {
            "kss_score": 4,
            "sleep_duration_band": "7–8小时",
            "assessment_attempt": "首次",
            "shift_type": "日班",
        }
        # 正确率恰好 0.80 不触发 low_accuracy（但因遗漏率超标仍建议复测）
        trials = [
            {
                "should_respond": index < 180,
                "outcome": "hit" if index < 124 else "omission",
                "reaction_time_s": 0.4 if index < 124 else None,
            }
            for index in range(160)
        ] + [
            {"should_respond": False, "outcome": "correct_rejection", "reaction_time_s": None}
            for _ in range(20)
        ]
        result = assess_readiness(context, trials, expected_trials=180, signal_quality_ok=True)
        self.assertEqual(result["metrics"]["accuracy"], 0.8)
        self.assertNotIn("low_accuracy", result["reason_codes"])
        self.assertEqual(result["status"], "retest")

        # 161/180 试次不足 90% → 无法评估；162/180 恰好 90% → 可评估
        short_trials = completed_trials()[:161]
        result = assess_readiness(context, short_trials, expected_trials=180, signal_quality_ok=True)
        self.assertEqual(result["status"], "unable")
        self.assertIn("insufficient_valid_trials", result["reason_codes"])
        enough_trials = completed_trials()[:162]
        result = assess_readiness(context, enough_trials, expected_trials=180, signal_quality_ok=True)
        self.assertNotIn("insufficient_valid_trials", result["reason_codes"])

    def test_invalid_or_missing_background_fields_yield_single_reason_codes(self) -> None:
        base_trials = completed_trials()
        missing_kss = assess_readiness(
            {
                "sleep_duration_band": "7–8小时",
                "assessment_attempt": "首次",
                "shift_type": "日班",
            },
            base_trials,
            expected_trials=180,
            signal_quality_ok=True,
        )
        self.assertEqual(missing_kss["status"], "unable")
        self.assertIn("missing_kss", missing_kss["reason_codes"])
        self.assertNotIn("invalid_kss", missing_kss["reason_codes"])

        invalid_shift = assess_readiness(
            {
                "kss_score": 4,
                "sleep_duration_band": "7–8小时",
                "assessment_attempt": "首次",
                "shift_type": "跨年夜班",
            },
            base_trials,
            expected_trials=180,
            signal_quality_ok=True,
        )
        self.assertEqual(invalid_shift["status"], "unable")
        self.assertIn("invalid_shift_type", invalid_shift["reason_codes"])


if __name__ == "__main__":
    unittest.main()
