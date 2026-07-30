"""
Centralized runtime configuration.

Architectural role
-------------------
Every tunable in this toolkit (paths, thresholds, chunk sizes, SLA windows)
flows through a single ``pydantic-settings`` object rather than being
hardcoded in business logic. This gives us:

1. A single source of truth that is trivially testable (construct a
   ``Settings`` object with overrides in a test, no monkeypatching env vars).
2. Twelve-factor-style configuration: every value can be overridden via
   environment variables (or a local ``.env`` file, see ``.env.example``)
   without touching code -- required for promoting the same container image
   from dev -> staging -> production.
3. A safe place to enforce "never hardcode secrets" -- there ARE no secrets
   in this demo (everything is mocked/offline), but the pattern is the same
   one you'd use to inject a real vector DB URL or API key in production.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root, used to resolve default sample-data paths regardless of
# the caller's current working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application-wide configuration, loaded from environment / .env.

    All fields have sane offline-friendly defaults so the toolkit runs
    out-of-the-box with zero configuration -- reviewers should be able to
    ``pip install -e .`` and immediately run CLI commands.
    """

    model_config = SettingsConfigDict(
        env_prefix="TOOLKIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General -----------------------------------------------------
    environment: str = Field(default="local", description="Deployment environment name.")
    log_level: str = Field(default="INFO", description="Python logging level.")
    log_format: str = Field(default="json", description="'json' or 'console'.")

    # --- Data locations (all default to bundled sample data) ---------
    sample_unstructured_dir: Path = Field(
        default=_REPO_ROOT / "data" / "sample_unstructured",
        description="Directory of synthetic .txt files for UnstructuredFileConnector.",
    )
    sample_db_path: Path = Field(
        default=_REPO_ROOT / "data" / "sample_bank.db",
        description="SQLite file used by RelationalDBConnector (auto-created if missing).",
    )
    state_dir: Path = Field(
        default=_REPO_ROOT / "data" / "state",
        description="Directory for pipeline run state: delta-index state, dead-letter store, audit log.",
    )

    # --- Chunking ------------------------------------------------------
    chunk_size: int = Field(default=400, description="Target chunk size (chars or tokens depending on strategy).")
    chunk_overlap: int = Field(default=50, description="Overlap between consecutive chunks.")

    # --- Indexing / freshness ------------------------------------------
    freshness_sla_hours: int = Field(
        default=24,
        description="A document not re-seen within this many hours is flagged 'stale' during reindex.",
    )

    # --- Governance ------------------------------------------------------
    default_retention_tag: str = Field(default="standard-7y", description="Default retention policy tag.")

    def index_state_path(self) -> Path:
        """Path to the JSON file tracking per-document checksums / last-seen timestamps."""
        return self.state_dir / "index_state.json"

    def dead_letter_path(self) -> Path:
        """Path to the JSONL dead-letter store for documents that fail validation."""
        return self.state_dir / "dead_letter.jsonl"

    def audit_log_path(self) -> Path:
        """Path to the JSONL audit log of pipeline run summaries."""
        return self.state_dir / "audit_log.jsonl"

    def ensure_state_dir(self) -> None:
        """Create the state directory on first use. Safe to call repeatedly."""
        self.state_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Factory used by CLI/tests instead of a shared global, keeping settings testable."""
    return Settings()
