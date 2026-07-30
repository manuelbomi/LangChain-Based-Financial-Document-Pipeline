"""Tests for the canonical DocumentMetadata schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from toolkit.metadata import DataClassification, DocumentMetadata, compute_checksum


def _valid_kwargs() -> dict:
    return {
        "source_system": "core-banking-api",
        "data_classification": DataClassification.INTERNAL,
        "effective_date": "2026-01-01",
        "retention_tag": "standard-7y",
        "content_checksum": compute_checksum("hello world"),
    }


def test_document_metadata_accepts_valid_payload() -> None:
    metadata = DocumentMetadata(**_valid_kwargs())
    assert metadata.data_classification is DataClassification.INTERNAL
    assert metadata.content_checksum == compute_checksum("hello world")


def test_document_metadata_rejects_missing_classification() -> None:
    kwargs = _valid_kwargs()
    del kwargs["data_classification"]
    with pytest.raises(ValidationError):
        DocumentMetadata(**kwargs)


def test_document_metadata_rejects_bad_checksum_shape() -> None:
    kwargs = _valid_kwargs()
    kwargs["content_checksum"] = "not-a-sha256-digest"
    with pytest.raises(ValidationError):
        DocumentMetadata(**kwargs)


def test_document_metadata_rejects_unknown_extra_field() -> None:
    kwargs = _valid_kwargs()
    kwargs["unexpected_field"] = "surprise"
    with pytest.raises(ValidationError):
        DocumentMetadata(**kwargs)


def test_compute_checksum_is_deterministic_and_content_sensitive() -> None:
    a = compute_checksum("some content")
    b = compute_checksum("some content")
    c = compute_checksum("different content")
    assert a == b
    assert a != c
    assert len(a) == 64
