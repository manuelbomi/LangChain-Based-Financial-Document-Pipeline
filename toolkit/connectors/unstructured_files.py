"""
Connector for a local directory of synthetic, loosely-structured `.txt`
files -- stands in for an unstructured document drop (shared drive, SFTP
landing zone, scanned-doc OCR output, etc.).

Architectural role
-------------------
Unlike the core-banking and relational-db connectors (which read from
structured sources with guaranteed fields), this connector demonstrates the
realistic case where source metadata is incomplete or malformed. It
deliberately does NOT fill in missing fields with defaults -- it reports
exactly what it found in ``raw_metadata``, leaving
``toolkit.validation.DataQualityValidator`` to decide whether gaps are fatal.
See ``data/sample_unstructured/README.txt`` for the tiny front-matter format
these sample files use.
"""

from __future__ import annotations

from pathlib import Path

from toolkit.connectors.base import ConnectorError, RawDocument, SourceConnector
from toolkit.logging_utils import get_logger

logger = get_logger(__name__)

SOURCE_NAME = "unstructured-files"

# Front-matter keys we recognize and how they map onto raw_metadata. Any
# other "KEY: value" header line is ignored; any of these that are simply
# absent from a file are left out of raw_metadata entirely (not defaulted),
# which is exactly what lets the validator exercise its "missing required
# metadata" dead-letter path against real sample data.
_HEADER_KEY_MAP = {
    "CLASSIFICATION": "data_classification",
    "EFFECTIVE_DATE": "effective_date",
    "RETENTION_TAG": "retention_tag",
}
_TITLE_KEY = "TITLE"
_HEADER_BODY_SEPARATOR = "---"


def _parse_front_matter(text: str) -> tuple[str, dict[str, str], str]:
    """Split a sample file into (title, raw_metadata, body).

    Format::

        TITLE: ...
        CLASSIFICATION: internal
        EFFECTIVE_DATE: 2026-01-01
        RETENTION_TAG: standard-7y
        ---
        <free-text body>

    Any header line may be omitted -- that's the point (see module docstring).
    """
    if _HEADER_BODY_SEPARATOR not in text:
        # No front matter at all: treat the whole file as body with no metadata.
        return "", {}, text.strip()

    header_block, body = text.split(_HEADER_BODY_SEPARATOR, 1)
    title = ""
    raw_metadata: dict[str, str] = {}
    for line in header_block.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().upper()
        value = value.strip()
        if key == _TITLE_KEY:
            title = value
        elif key in _HEADER_KEY_MAP:
            raw_metadata[_HEADER_KEY_MAP[key]] = value
    return title, raw_metadata, body.strip()


class UnstructuredFileConnector(SourceConnector):
    """Reads every ``*.txt`` file in a directory as one document."""

    source_name = SOURCE_NAME

    def __init__(self, directory: Path | str | None = None) -> None:
        from toolkit.config import get_settings

        self._directory = Path(directory) if directory is not None else get_settings().sample_unstructured_dir
        if not self._directory.exists():
            raise ConnectorError(f"unstructured file directory does not exist: {self._directory}")

    def _files(self) -> list[Path]:
        # README.txt documents the sample-data format for humans; it is not
        # itself a pipeline document, so it's excluded from ingestion.
        return sorted(p for p in self._directory.glob("*.txt") if p.stem.upper() != "README")

    def list_documents(self) -> list[str]:
        # Document ID is the filename stem -- stable, human-readable, and
        # deterministic across runs (important for delta indexing).
        return [p.stem for p in self._files()]

    def fetch(self, doc_id: str) -> RawDocument:
        path = self._directory / f"{doc_id}.txt"
        if not path.exists():
            raise ConnectorError(f"document not found in unstructured directory: {doc_id}")

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConnectorError(f"failed reading {path}: {exc}") from exc

        title, raw_metadata, body = _parse_front_matter(text)
        return RawDocument(
            doc_id=doc_id,
            title=title or doc_id,
            content=body,
            source_system=SOURCE_NAME,
            raw_metadata=raw_metadata,
        )
