import tomllib
import unittest
from pathlib import Path

from bsense_experiment import __version__


class VersionTests(unittest.TestCase):
    def test_package_and_project_versions_match(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with (project_root / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)
        self.assertEqual(project["project"]["version"], __version__)


if __name__ == "__main__":
    unittest.main()
