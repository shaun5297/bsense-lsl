from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

from bsense_experiment.resources import application_resource_root, object_asset_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_release_module():
    module_path = PROJECT_ROOT / "tools" / "build_release.py"
    spec = importlib.util.spec_from_file_location("build_release", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResourceTests(unittest.TestCase):
    def test_source_resource_root_is_project_root(self) -> None:
        self.assertEqual(application_resource_root(), PROJECT_ROOT)

    def test_required_object_assets_resolve(self) -> None:
        for filename in ("cup.png", "medicinebottle.png", "mobilephone.png"):
            self.assertTrue(object_asset_path(filename).is_file())


class ReleaseBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.release = load_release_module()

    def test_project_version_and_archive_name(self) -> None:
        self.assertEqual(self.release.project_version(), "0.8.0")
        self.assertEqual(
            self.release.archive_basename("0.8.0", "windows", "x64"),
            "BSense-LSL-0.8.0-windows-x64",
        )

    def test_required_release_sources_exist(self) -> None:
        self.release.verify_sources()

    def test_macos_bundle_identifier_is_reverse_dns(self) -> None:
        self.assertEqual(
            self.release.MACOS_BUNDLE_IDENTIFIER,
            "io.github.shaun5297.bsense-lsl",
        )

    def test_archive_verifier_rejects_incomplete_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "incomplete.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("README.txt", "incomplete")
            with self.assertRaisesRegex(RuntimeError, "ZIP 缺少发行内容"):
                self.release.verify_archive(archive_path, "windows")


if __name__ == "__main__":
    unittest.main()
