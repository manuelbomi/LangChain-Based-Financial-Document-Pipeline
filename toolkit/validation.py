"""
Data-quality validation gate and dead-letter routing.

Architectural role
-------------------
Every ``RawDocument`` a connector produces passes through
``DataQualityValidator.validate`` before it is allowed to become a strict,
schema-conformant ``DocumentRecord`` that the rest of the pipeline can trust.
This is the single choke point that enforces governance requirements:

- Required governance metadata (classification, effective date, retention
  tag) must be present -- documents missing it are routed to the
  **dead-letter store** with a human-readable reason, never silently
  dropped or silently indexed.
- PII-shaped content is **flagged, not silently dropped or redacted** --
  callers (CLI/audit log) decide what to do with the flag. Silently
  stripping PII would hide a data-quality problem from the humans who need
  to know about it; silently indexing it would be a governance failure.
- Duplicate content (same checksum, different doc_id) within a batch is
  routed to the dead-letter store too, so downstream indexes don't carry
  redundant chunks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from toolkit.connectors.base import RawDocument
from toolkit.logging_utils import get_logger
from toolkit.metadata import DataClassification, DocumentMetadata, DocumentRecord, compute_checksum, utcnow

logger = get_logger(__name__)

#: Governance metadata every document must carry to proceed past validation.
REQUIRED_RAW_METADATA_FIELDS = ("data_classification", "effective_date", "retention_tag")

# Illustrative PII pattern flags -- intentionally simple regexes, NOT a
# production-grade PII detector (no NER model, no Luhn checksum validation).
# The point is to demonstrate the "flag, don't silently drop" governance
# pattern; a real deployment would plug in a proper PII scanning service here
# behind the same interface.
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "account_number_like": re.compile(r"\b\d{9,12}\b"),
}


@dataclass
class ValidationOutcome:
    """Result of validating one ``RawDocument``."""

    document: DocumentRecord | None
    pii_flags: list[str]
    rejected: bool
    rejection_reason: str | None


class DeadLetterStore:
    """Append-only JSONL store of documents that failed validation.

    JSONL (one JSON object per line) is used instead of a single JSON array
    so the file can be safely appended to across many pipeline runs without
    ever needing to parse-and-rewrite the whole file.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, doc_id: str, source_system: str, reason: str, run_id: str) -> None:
        entry = {
            "doc_id": doc_id,
            "source_system": source_system,
            "reason": reason,
            "run_id": run_id,
            "recorded_at": utcnow().isoformat(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        logger.warning(
            "document_dead_lettered",
            extra={"fields": {"doc_id": doc_id, "source_system": source_system, "reason": reason}},
        )

    def list_entries(self) -> list[dict]:
        """Read back every dead-letter entry ever recorded (used by the CLI)."""
        if not self._path.exists():
            return []
        entries: list[dict] = []
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries


class DataQualityValidator:
    """Validates ``RawDocument`` -> ``DocumentRecord`` and routes failures.

    Duplicate-checksum detection is scoped to documents seen by *this*
    validator instance (i.e. within one pipeline run's batch) -- deduping
    against everything ever indexed is the delta index's job
    (``toolkit.indexing``), which persists checksums across runs.
    """

    def __init__(self, dead_letter_store: DeadLetterStore, run_id: str = "unset") -> None:
        self._dead_letter = dead_letter_store
        self._run_id = run_id
        self._seen_checksums: dict[str, str] = {}

    def validate(self, raw: RawDocument) -> ValidationOutcome:
        # 1. Required-field check -- the most common real-world failure mode
        #    for an unstructured intake source.
        missing = [field for field in REQUIRED_RAW_METADATA_FIELDS if not raw.raw_metadata.get(field)]
        if not raw.content.strip():
            missing.append("content")
        if missing:
            reason = f"missing required fields: {', '.join(missing)}"
            self._dead_letter.record(raw.doc_id, raw.source_system, reason, self._run_id)
            return ValidationOutcome(document=None, pii_flags=[], rejected=True, rejection_reason=reason)

        checksum = compute_checksum(raw.content)

        # 2. Duplicate detection by checksum (within this batch).
        if checksum in self._seen_checksums and self._seen_checksums[checksum] != raw.doc_id:
            reason = f"duplicate content checksum (matches {self._seen_checksums[checksum]})"
            self._dead_letter.record(raw.doc_id, raw.source_system, reason, self._run_id)
            return ValidationOutcome(document=None, pii_flags=[], rejected=True, rejection_reason=reason)

        # 3. Type/format validation -- catches e.g. an unparseable date or an
        #    unrecognized classification value that slipped past field-presence.
        try:
            metadata = DocumentMetadata(
                source_system=raw.source_system,
                data_classification=DataClassification(raw.raw_metadata["data_classification"]),
                effective_date=date.fromisoformat(str(raw.raw_metadata["effective_date"])),
                retention_tag=str(raw.raw_metadata["retention_tag"]),
                content_checksum=checksum,
            )
        except (ValidationError, ValueError) as exc:
            reason = f"invalid metadata: {exc}"
            self._dead_letter.record(raw.doc_id, raw.source_system, reason, self._run_id)
            return ValidationOutcome(document=None, pii_flags=[], rejected=True, rejection_reason=reason)

        self._seen_checksums[checksum] = raw.doc_id

        # 4. PII pattern flags -- surfaced on the outcome (and logged), the
        #    document still proceeds. Governance policy for *what happens*
        #    to flagged documents (extra review queue, masking before
        #    indexing, etc.) is intentionally left to the calling
        #    application/policy layer -- this toolkit's job is to make sure
        #    the signal is never lost.
        pii_flags = [name for name, pattern in _PII_PATTERNS.items() if pattern.search(raw.content)]
        if pii_flags:
            logger.warning(
                "pii_pattern_flagged",
                extra={"fields": {"doc_id": raw.doc_id, "flags": pii_flags}},
            )

        document = DocumentRecord(doc_id=raw.doc_id, title=raw.title, content=raw.content, metadata=metadata)
        return ValidationOutcome(document=document, pii_flags=pii_flags, rejected=False, rejection_reason=None)
