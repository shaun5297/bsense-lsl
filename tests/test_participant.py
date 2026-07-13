import json
import tempfile
import unittest
from pathlib import Path

from bsense_experiment.participant import save_participant_profile, validate_participant_profile


class ParticipantProfileTests(unittest.TestCase):
    def test_profile_validation_and_persistence(self) -> None:
        profile = validate_participant_profile(
            name="测试被试",
            age="72",
            sex="女",
            education_years="12",
            dominant_hand="右",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, created = save_participant_profile(root, "pilot01", "01", profile, "0.4.0")
            second_path, second_created = save_participant_profile(root, "pilot01", "01", profile, "0.4.0")
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertTrue(created)
            self.assertFalse(second_created)
            self.assertEqual(path, second_path)
            self.assertEqual(payload["name"], "测试被试")
            self.assertEqual(payload["age"], 72)
            self.assertTrue(payload["consent_confirmed"])

    def test_existing_profile_rejects_conflicting_identity(self) -> None:
        profile = validate_participant_profile(
            name="甲",
            age="70",
            sex="男",
            education_years="",
            dominant_hand="左",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_participant_profile(root, "pilot01", "01", profile, "0.4.0")
            changed = {**profile, "age": 71}
            with self.assertRaises(ValueError):
                save_participant_profile(root, "pilot01", "01", changed, "0.4.0")

    def test_invalid_age_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_participant_profile(
                name="",
                age="unknown",
                sex="不愿透露",
                education_years="",
                dominant_hand="右",
            )


if __name__ == "__main__":
    unittest.main()
