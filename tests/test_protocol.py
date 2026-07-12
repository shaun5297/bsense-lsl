import unittest

from bsense_experiment.app import (
    build_deviceqc_plan,
    build_xdf_filename,
    validate_identifier,
)


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


if __name__ == "__main__":
    unittest.main()

