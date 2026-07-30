"""Tests for delta/incremental indexing: skip unchanged, reprocess changed, staleness."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from toolkit.indexing import DeltaIndex
from toolkit.metadata import DataClassification, DocumentMetadata, DocumentRecord, compute_checksum, utcnow


def _make_document(doc_id: str, content: str) -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        title="Title",
        content=content,
        metadata=DocumentMetadata(
            source_system="unit-test",
            data_classification=DataClassification.INTERNAL,
            effective_date="2026-01-01",
            retention_tag="standard-7y",
            content_checksum=compute_checksum(content),
        ),
    )


def test_new_document_is_evaluated_as_new(tmp_path: Path) -> None:
    index = DeltaIndex(tmp_path / "state.json")
    doc = _make_document("doc-1", "hello world")
    assert index.evaluate(doc) == "new"


def test_unchanged_document_is_skipped_after_recording(tmp_path: Path) -> None:
    index = DeltaIndex(tmp_path / "state.json")
    doc = _make_document("doc-1", "hello world")
    index.record_processed(doc, chunk_count=2)

    same_doc = _make_document("doc-1", "hello world")  # identical content -> identical checksum
    assert index.evaluate(same_doc) == "unchanged"


def test_changed_document_is_flagged_for_reprocessing(tmp_path: Path) -> None:
    index = DeltaIndex(tmp_path / "state.json")
    original = _make_document("doc-1", "version one")
    index.record_processed(original, chunk_count=1)

    changed = _make_document("doc-1", "version two -- content actually changed")
    assert index.evaluate(changed) == "changed"


def test_state_persists_across_deltaindex_instances(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    doc = _make_document("doc-1", "hello world")
    DeltaIndex(state_path).record_processed(doc, chunk_count=3)

    reloaded = DeltaIndex(state_path)
    entry = reloaded.get("doc-1")
    assert entry is not None
    assert entry.checksum == doc.metadata.content_checksum
    assert entry.chunk_count == 3


def test_touch_unchanged_updates_last_seen_without_changing_checksum(tmp_path: Path) -> None:
    index = DeltaIndex(tmp_path / "state.json")
    doc = _make_document("doc-1", "hello world")
    index.record_processed(doc, chunk_count=1)
    original_last_seen = index.get("doc-1").last_seen

    index.touch_unchanged(doc)
    updated_entry = index.get("doc-1")
    assert updated_entry.checksum == doc.metadata.content_checksum
    assert updated_entry.last_seen >= original_last_seen


def test_stale_doc_ids_flags_documents_past_freshness_sla(tmp_path: Path) -> None:
    index = DeltaIndex(tmp_path / "state.json", freshness_sla_hours=1)
    doc = _make_document("doc-1", "hello world")
    index.record_processed(doc, chunk_count=1)

    # Evaluate staleness as of 2 hours later (past the 1-hour SLA).
    future = utcnow() + timedelta(hours=2)
    assert index.stale_doc_ids(as_of=future) == ["doc-1"]


def test_stale_doc_ids_excludes_recently_seen_documents(tmp_path: Path) -> None:
    index = DeltaIndex(tmp_path / "state.json", freshness_sla_hours=24)
    doc = _make_document("doc-1", "hello world")
    index.record_processed(doc, chunk_count=1)

    just_after = utcnow() + timedelta(minutes=5)
    assert index.stale_doc_ids(as_of=just_after) == []
