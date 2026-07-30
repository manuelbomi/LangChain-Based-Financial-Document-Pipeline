"""End-to-end pipeline tests wiring connectors -> validation -> chunking ->
metadata enrichment -> delta indexing together, using the bundled sample
data. These exercise the DAG runner and confirm the dead-letter and
delta-indexing behaviors observed in isolation also hold when composed.
"""

from __future__ import annotations

from datetime import date

from toolkit.config import Settings
from toolkit.pipeline import run_pipeline
from toolkit.validation import DeadLetterStore


def test_unstructured_files_pipeline_dead_letters_incomplete_document(settings: Settings) -> None:
    summary = run_pipeline(settings, source="unstructured-files", strategy="recursive")

    assert summary.docs_seen == 5  # 5 sample files (README.txt is excluded by the connector)
    assert summary.docs_failed_validation == 1  # northbridge_incomplete_upload.txt
    assert summary.docs_indexed == 4

    dead_letter_entries = DeadLetterStore(settings.dead_letter_path()).list_entries()
    dead_lettered_ids = {entry["doc_id"] for entry in dead_letter_entries}
    assert "northbridge_incomplete_upload" in dead_lettered_ids


def test_unstructured_files_pipeline_flags_pii_without_rejecting(settings: Settings) -> None:
    summary = run_pipeline(settings, source="unstructured-files", strategy="recursive")
    assert "northbridge_kyc_procedure" in summary.pii_flagged_doc_ids


def test_second_run_skips_unchanged_documents(settings: Settings) -> None:
    first = run_pipeline(settings, source="core-banking", strategy="recursive")
    assert first.docs_indexed == 3
    assert first.docs_skipped_unchanged == 0

    second = run_pipeline(settings, source="core-banking", strategy="recursive")
    assert second.docs_indexed == 0
    assert second.docs_skipped_unchanged == 3


def test_reindex_since_filters_out_older_documents(settings: Settings) -> None:
    # cb-doc-001 effective 2026-01-01, cb-doc-002 2026-02-15, cb-doc-003 2026-03-01.
    summary = run_pipeline(settings, source="core-banking", strategy="recursive", since=date(2026, 3, 1))
    assert summary.docs_indexed == 1
