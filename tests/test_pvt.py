import unittest

from bsense_experiment.pvt import classify_pvt_response, summarize_pvt_trials


class PVTTests(unittest.TestCase):
    def test_response_classification_uses_brief_pvt_thresholds(self) -> None:
        self.assertEqual(classify_pvt_response(0.099)["outcome"], "false_start")
        self.assertEqual(classify_pvt_response(0.1)["outcome"], "hit")
        self.assertEqual(classify_pvt_response(0.354)["outcome"], "hit")
        self.assertEqual(classify_pvt_response(0.355)["outcome"], "lapse")
        self.assertEqual(
            classify_pvt_response(None, stimulus_present=False)["outcome"],
            "false_start",
        )
        self.assertEqual(
            classify_pvt_response(30.0, timed_out=True)["outcome"],
            "timeout",
        )

    def test_summary_excludes_invalidated_and_truncated_trials(self) -> None:
        summary = summarize_pvt_trials(
            [
                {
                    "outcome": "hit",
                    "stimulus_present": True,
                    "reaction_time_s": 0.25,
                },
                {
                    "outcome": "lapse",
                    "stimulus_present": True,
                    "reaction_time_s": 0.5,
                },
                {
                    "outcome": "false_start",
                    "stimulus_present": False,
                    "reaction_time_s": None,
                },
                {
                    "outcome": "lapse",
                    "stimulus_present": True,
                    "reaction_time_s": 0.8,
                    "invalidated": True,
                },
                {
                    "outcome": "truncated",
                    "stimulus_present": True,
                    "reaction_time_s": None,
                },
            ]
        )
        self.assertEqual(summary["event_count"], 3)
        self.assertEqual(summary["trial_count"], 2)
        self.assertEqual(summary["stimulus_count"], 2)
        self.assertEqual(summary["lapse_count"], 1)
        self.assertEqual(summary["false_start_count"], 1)
        self.assertEqual(summary["mean_reaction_time_s"], 0.375)


if __name__ == "__main__":
    unittest.main()
