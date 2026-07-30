"""Tests for the data-quality validator and dead-letter routing."""

from __future__ import annotations

from pathlib import Path

from toolkit.connectors.base import RawDocument
from toolkit.validation import DataQualityValidator, DeadLetterStore


def _raw(doc_id: str, content: str = "some content", **metadata_overrides) -> RawDocument:
    raw_metadata = {
        "data_classification": "internal",
        "effective_date": "2026-01-01",
        "retention_tag": "standard-7y",
    }
    raw_metadata.update(metadata_overrides)
    return RawDocument(
        doc_id=doc_id, title="Title", content=content, source_system="unit-test", raw_metadata=raw_metadata
    )


def test_valid_document_passes_and_is_not_dead_lettered(tmp_path: Path) -> None:
    store = DeadLetterStore(tmp_path / "dlq.jsonl")
    validator = DataQualityValidator(store, run_id="run-1")

    outcome = validator.validate(_raw("doc-1"))

    assert outcome.rejected is False
    assert outcome.document is not None
    assert outcome.document.doc_id == "doc-1"
    assert store.list_entries() == []


def test_document_missing_required_metadata_is_dead_lettered(tmp_path: Path) -> None:
    store = DeadLetterStore(tmp_path / "dlq.jsonl")
    validator = DataQualityValidator(store, run_id="run-1")

    raw = RawDocument(
        doc_id="doc-missing",
        title="Incomplete",
        content="body text",
        source_system="unit-test",
        raw_metadata={},  # classification / effective_date / retention_tag all absent
    )
    outcome = validator.validate(raw)

    assert outcome.rejected is True
    assert outcome.document is None
    assert "missing required fields" in outcome.rejection_reason

    entries = store.list_entries()
    assert len(entries) == 1
    assert entries[0]["doc_id"] == "doc-missing"
    assert "data_classification" in entries[0]["reason"]


def test_document_with_empty_content_is_dead_lettered(tmp_path: Path) -> None:
    store = DeadLetterStore(tmp_path / "dlq.jsonl")
    validator = DataQualityValidator(store, run_id="run-1")

    outcome = validator.validate(_raw("doc-empty", content="   "))
    assert outcome.rejected is True
    assert "content" in outcome.rejection_reason


def test_invalid_classification_value_is_dead_lettered(tmp_path: Path) -> None:
    store = DeadLetterStore(tmp_path / "dlq.jsonl")
    validator = DataQualityValidator(store, run_id="run-1")

    outcome = validator.validate(_raw("doc-bad-class", data_classification="not-a-real-tier"))
    assert outcome.rejected is True
    assert "invalid metadata" in outcome.rejection_reason


def test_duplicate_checksum_across_doc_ids_is_dead_lettered(tmp_path: Path) -> None:
    store = DeadLetterStore(tmp_path / "dlq.jsonl")
    validator = DataQualityValidator(store, run_id="run-1")

    first = validator.validate(_raw("doc-a", content="identical content"))
    second = validator.validate(_raw("doc-b", content="identical content"))

    assert first.rejected is False
    assert second.rejected is True
    assert "duplicate content checksum" in second.rejection_reason


def test_pii_pattern_flags_are_surfaced_not_dropped(tmp_path: Path) -> None:
    store = DeadLetterStore(tmp_path / "dlq.jsonl")
    validator = DataQualityValidator(store, run_id="run-1")

    outcome = validator.validate(_raw("doc-pii", content="Example SSN for testing: 123-45-6789."))

    assert outcome.rejected is False  # flagged, NOT rejected
    assert outcome.document is not None
    assert "ssn_like" in outcome.pii_flags


def test_document_without_pii_has_no_flags(tmp_path: Path) -> None:
    store = DeadLetterStore(tmp_path / "dlq.jsonl")
    validator = DataQualityValidator(store, run_id="run-1")

    outcome = validator.validate(_raw("doc-clean", content="No sensitive patterns here at all."))
    assert outcome.pii_flags == []


def test_dead_letter_store_list_entries_is_empty_when_file_missing(tmp_path: Path) -> None:
    store = DeadLetterStore(tmp_path / "does_not_exist.jsonl")
    assert store.list_entries() == []
