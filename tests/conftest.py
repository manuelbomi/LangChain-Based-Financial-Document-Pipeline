"""Shared pytest fixtures.

Every test that touches filesystem state (SQLite sample DB, delta-index
state, dead-letter store, audit log) gets an isolated ``tmp_path`` via the
``settings`` fixture, so tests never depend on execution order or leak
state into the repo's real ``data/`` directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A Settings instance pointed entirely at a scratch tmp_path directory."""
    return Settings(
        sample_unstructured_dir=REPO_ROOT / "data" / "sample_unstructured",
        sample_db_path=tmp_path / "sample_bank.db",
        state_dir=tmp_path / "state",
    )
