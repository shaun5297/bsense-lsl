"""Locate application resources in source and frozen distributions."""

from __future__ import annotations

import sys
from pathlib import Path


def application_resource_root() -> Path:
    """Return the package root containing application data."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "bsense_experiment"
    return Path(__file__).resolve().parent


def object_asset_path(filename: str) -> Path:
    """Return an object-cue image path for source and frozen applications."""

    return application_resource_root() / "assets" / filename
