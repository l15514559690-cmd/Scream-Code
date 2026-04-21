"""Shared helper for archive placeholder packages."""

from __future__ import annotations

import json
from pathlib import Path


def load_archive_metadata(package_name: str) -> dict:
    """Load archive metadata from reference_data/subsystems/{package_name}.json."""
    snapshot_path = (
        Path(__file__).resolve().parent
        / "reference_data"
        / "subsystems"
        / f"{package_name}.json"
    )
    return json.loads(snapshot_path.read_text())
