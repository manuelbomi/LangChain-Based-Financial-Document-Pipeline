"""
Canonical document + metadata schemas shared across every layer.

Architectural role
-------------------
``DocumentMetadata`` is the single contract that connectors produce and that
validation/chunking/indexing all consume. Centralizing it here (rather than
letting each connector invent its own shape) is what makes the pipeline
layers composable: validation doesn't need to know which connector a
document came from, it just needs a valid ``DocumentMetadata``.

Governance note: ``data_classification`` is a MANDATORY field (no default of
"public") on every ingested document -- see GOVERNANCE.md. A financial
institution's data-loss-prevention posture depends on every document in the
pipeline carrying an explicit classification tag rather than an implicit
assumption.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DataClassification(str, Enum):
    """Financial-services-style data sensitivity tiers.

    Ordered loosely from least to most sensitive. Used to drive downstream
    handling decisions (e.g. which documents are eligible for a
    lower-trust/third-party vector store vs. an on-prem-only index) --
    that routing logic is out of scope for this toolkit but the tag is the
    hook a real deployment would key off of.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class DocumentMetadata(BaseModel):
    """Mandatory metadata envelope attached to every document in the pipeline.

    This is deliberately a *strict* model (``extra="forbid"``) -- a schema
    reviewers can trust to be complete, and a good place to catch a
    connector bug (typo'd field name) at ingestion time rather than three
    stages later.
    """

    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(..., min_length=1, description="Origin system, e.g. 'core-banking-api'.")
    data_classification: DataClassification = Field(
        ..., description="Mandatory sensitivity tag; never defaulted implicitly."
    )
    effective_date: date = Field(..., description="Business-effective date of the document content.")
    retention_tag: str = Field(..., min_length=1, description="Records-retention policy identifier.")
    content_checksum: str = Field(..., description="SHA-256 hex digest of the document content.")

    @field_validator("content_checksum")
    @classmethod
    def _checksum_looks_like_sha256(cls, v: str) -> str:
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v.lower()):
            raise ValueError("content_checksum must be a 64-char hex SHA-256 digest")
        return v.lower()


class DocumentRecord(BaseModel):
    """A full document as it flows through the pipeline: id + content + metadata."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(..., min_length=1)
    title: str = Field(default="")
    content: str = Field(default="")
    metadata: DocumentMetadata


def compute_checksum(content: str) -> str:
    """SHA-256 hex digest of document content, used for dedupe + delta indexing.

    Centralized here so every caller (connectors, tests, indexing) hashes
    content identically -- utf-8 encoding, no normalization surprises.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    """Single source of truth for 'now' so tests can monkeypatch this instead of datetime.now."""
    return datetime.now(UTC)
