import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from bsense_experiment.platform_support import (
    VOICE_CUE_TEXTS,
    default_output_root,
    find_labrecorder_app,
    play_audio_cue,
    ui_font_family,
    voice_cue_path,
)


class PlatformSupportTests(unittest.TestCase):
    def test_macos_defaults_are_native(self) -> None:
        home = Path("/Users/tester")
        self.assertEqual(
            default_output_root(platform="darwin", home=home),
            home / "Documents" / "BCI" / "data" / "bsense",
        )
        self.assertEqual(ui_font_family(platform="darwin"), "PingFang SC")

    def test_windows_default_is_preserved(self) -> None:
        self.assertEqual(default_output_root(platform="win32"), Path(r"C:\BCI\data\bsense"))

    def test_find_labrecorder_app_validates_bundle_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app_path = Path(directory) / "LabRecorder.app"
            executable = app_path / "Contents" / "MacOS" / "LabRecorder"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch("bsense_experiment.platform_support.sys.platform", "darwin"):
                self.assertEqual(find_labrecorder_app([app_path]), app_path.resolve())

    def test_find_labrecorder_app_is_macos_only(self) -> None:
        with patch("bsense_experiment.platform_support.sys.platform", "linux"):
            self.assertIsNone(find_labrecorder_app([]))

    def test_all_voice_cues_are_packaged_pcm_wav_files(self) -> None:
        for cue in VOICE_CUE_TEXTS:
            path = voice_cue_path(cue)
            self.assertTrue(path.is_file(), path)
            with wave.open(str(path), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertEqual(audio.getframerate(), 24_000)

    def test_macos_voice_cue_uses_cached_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            player = Path(directory) / "afplay"
            player.touch()
            with (
                patch("bsense_experiment.platform_support.sys.platform", "darwin"),
                patch("bsense_experiment.platform_support.MACOS_AFPLAY", player),
                patch("bsense_experiment.platform_support._ACTIVE_MACOS_PROCESS", None),
                patch("bsense_experiment.platform_support.subprocess.Popen") as popen,
            ):
                self.assertTrue(play_audio_cue("start"))
            popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
