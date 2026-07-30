"""
Incremental / delta indexing: skip reprocessing unchanged documents, and
flag documents that haven't been re-seen within a freshness SLA as stale.

Architectural role
-------------------
Re-chunking and re-embedding every document on every pipeline run is
wasteful and, at bank scale, expensive. ``DeltaIndex`` persists a per-document
content checksum plus timestamps to a small JSON state file, so a reindex
run can cheaply decide, per document:

- **new**       -- never indexed before, must be processed
- **changed**   -- content checksum differs from last time, must be reprocessed
- **unchanged** -- checksum matches, safe to skip re-chunking entirely

It also tracks *staleness*: a document that used to be indexed but hasn't
been re-seen by any connector within ``freshness_sla_hours`` (e.g. because
it was deleted at the source, or a scheduled job stopped running) is flagged
so operators can investigate rather than silently serving increasingly
out-of-date retrieval results.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from toolkit.logging_utils import get_logger
from toolkit.metadata import DocumentRecord, utcnow

logger = get_logger(__name__)

DeltaAction = Literal["new", "changed", "unchanged"]


class IndexEntry(BaseModel):
    """Persisted per-document state tracked by the delta index."""

    checksum: str
    last_seen: datetime
    indexed_at: datetime
    chunk_count: int = 0


class DeltaIndex:
    """JSON-file-backed delta index.

    A JSON file (rather than SQLite) is a deliberate simplicity choice for
    this toolkit's scale (demo-sized document sets); the interface is small
    enough that swapping in a real key-value store or a table in the target
    vector DB later is a contained change -- see README "Roadmap".
    """

    def __init__(self, state_path: Path, freshness_sla_hours: int = 24) -> None:
        self._path = state_path
        self._freshness_sla = timedelta(hours=freshness_sla_hours)
        self._state: dict[str, IndexEntry] = self._load()

    def _load(self) -> dict[str, IndexEntry]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return {doc_id: IndexEntry(**entry) for doc_id, entry in raw.items()}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {doc_id: json.loads(entry.model_dump_json()) for doc_id, entry in self._state.items()}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def evaluate(self, document: DocumentRecord) -> DeltaAction:
        """Decide whether ``document`` needs (re)processing, without mutating state."""
        prior = self._state.get(document.doc_id)
        if prior is None:
            return "new"
        if prior.checksum != document.metadata.content_checksum:
            return "changed"
        return "unchanged"

    def record_processed(self, document: DocumentRecord, chunk_count: int) -> None:
        """Persist state after a document has been (re)chunked and (re)indexed."""
        now = utcnow()
        self._state[document.doc_id] = IndexEntry(
            checksum=document.metadata.content_checksum,
            last_seen=now,
            indexed_at=now,
            chunk_count=chunk_count,
        )
        self._save()
        logger.info(
            "document_indexed",
            extra={"fields": {"doc_id": document.doc_id, "chunk_count": chunk_count}},
        )

    def touch_unchanged(self, document: DocumentRecord) -> None:
        """Update ``last_seen`` for a document whose content didn't change.

        This is what keeps an unchanged-but-still-present document from
        being incorrectly flagged stale -- the connector saw it again this
        run, it just didn't need re-chunking.
        """
        prior = self._state.get(document.doc_id)
        if prior is not None:
            self._state[document.doc_id] = prior.model_copy(update={"last_seen": utcnow()})
            self._save()

    def stale_doc_ids(self, as_of: datetime | None = None) -> list[str]:
        """Return doc_ids whose last_seen exceeds the freshness SLA window."""
        now = as_of or utcnow()
        return [doc_id for doc_id, entry in self._state.items() if now - entry.last_seen > self._freshness_sla]

    def get(self, doc_id: str) -> IndexEntry | None:
        return self._state.get(doc_id)

    def all_entries(self) -> dict[str, IndexEntry]:
        return dict(self._state)
