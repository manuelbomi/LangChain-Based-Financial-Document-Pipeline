"""Tests for each SourceConnector: expected document count and content shape."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.connectors.base import ConnectorError
from toolkit.connectors.core_banking import CoreBankingAPIConnector
from toolkit.connectors.relational_db import RelationalDBConnector
from toolkit.connectors.unstructured_files import UnstructuredFileConnector

# --- CoreBankingAPIConnector -------------------------------------------------


def test_core_banking_connector_lists_expected_documents() -> None:
    connector = CoreBankingAPIConnector()
    doc_ids = connector.list_documents()
    assert doc_ids == ["cb-doc-001", "cb-doc-002", "cb-doc-003"]


def test_core_banking_connector_fetch_returns_northbridge_content() -> None:
    connector = CoreBankingAPIConnector()
    raw = connector.fetch("cb-doc-001")
    assert raw.source_system == "core-banking-api"
    assert "Northbridge Financial Group" in raw.content
    assert raw.raw_metadata["data_classification"] == "internal"
    assert raw.raw_metadata["effective_date"] == "2026-01-01"


def test_core_banking_connector_unknown_doc_raises_connector_error() -> None:
    connector = CoreBankingAPIConnector()
    with pytest.raises(ConnectorError):
        connector.fetch("does-not-exist")


def test_core_banking_connector_retries_then_succeeds_on_transient_failure() -> None:
    # failure_rate=1.0 with a fixed seed means every call raises the
    # simulated transient error; tenacity retries up to 4 attempts and then
    # re-raises -- exercised here via ConnectorError after retries exhausted.
    connector = CoreBankingAPIConnector(failure_rate=1.0, seed=1)
    with pytest.raises(ConnectorError):
        connector.fetch("cb-doc-001")


def test_core_banking_connector_fetch_all_returns_all_documents() -> None:
    connector = CoreBankingAPIConnector()
    docs = connector.fetch_all()
    assert len(docs) == 3
    assert {d.doc_id for d in docs} == {"cb-doc-001", "cb-doc-002", "cb-doc-003"}


# --- RelationalDBConnector ---------------------------------------------------


def test_relational_db_connector_auto_seeds_and_lists_documents(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.db"
    connector = RelationalDBConnector(db_path=db_path)
    assert db_path.exists()
    doc_ids = connector.list_documents()
    assert doc_ids == ["rdb-doc-001", "rdb-doc-002", "rdb-doc-003", "rdb-doc-004"]


def test_relational_db_connector_fetch_returns_expected_row(tmp_path: Path) -> None:
    connector = RelationalDBConnector(db_path=tmp_path / "sample.db")
    raw = connector.fetch("rdb-doc-002")
    assert raw.title == "Northbridge Financial Group -- Mortgage Rate Disclosure"
    assert raw.raw_metadata["data_classification"] == "public"


def test_relational_db_connector_is_idempotent_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.db"
    RelationalDBConnector(db_path=db_path)
    second = RelationalDBConnector(db_path=db_path)  # re-seeding must not duplicate rows
    assert len(second.list_documents()) == 4


def test_relational_db_connector_unknown_doc_raises_connector_error(tmp_path: Path) -> None:
    connector = RelationalDBConnector(db_path=tmp_path / "sample.db")
    with pytest.raises(ConnectorError):
        connector.fetch("does-not-exist")


# --- UnstructuredFileConnector ------------------------------------------------


def test_unstructured_file_connector_lists_txt_files_excluding_readme(tmp_path: Path) -> None:
    directory = tmp_path / "docs"
    directory.mkdir()
    (directory / "a.txt").write_text("TITLE: A\nCLASSIFICATION: public\nEFFECTIVE_DATE: 2026-01-01\n"
                                      "RETENTION_TAG: standard-7y\n---\nHello world.")
    (directory / "README.txt").write_text("not a document")
    connector = UnstructuredFileConnector(directory=directory)
    assert connector.list_documents() == ["a"]


def test_unstructured_file_connector_parses_front_matter(tmp_path: Path) -> None:
    directory = tmp_path / "docs"
    directory.mkdir()
    (directory / "sample.txt").write_text(
        "TITLE: Sample Doc\nCLASSIFICATION: confidential\nEFFECTIVE_DATE: 2026-05-01\n"
        "RETENTION_TAG: standard-7y\n---\nBody text here."
    )
    connector = UnstructuredFileConnector(directory=directory)
    raw = connector.fetch("sample")
    assert raw.title == "Sample Doc"
    assert raw.content == "Body text here."
    assert raw.raw_metadata == {
        "data_classification": "confidential",
        "effective_date": "2026-05-01",
        "retention_tag": "standard-7y",
    }


def test_unstructured_file_connector_reports_missing_fields_as_absent(tmp_path: Path) -> None:
    directory = tmp_path / "docs"
    directory.mkdir()
    (directory / "incomplete.txt").write_text("TITLE: Missing Fields\n---\nBody only.")
    connector = UnstructuredFileConnector(directory=directory)
    raw = connector.fetch("incomplete")
    assert "data_classification" not in raw.raw_metadata
    assert "effective_date" not in raw.raw_metadata


def test_unstructured_file_connector_bundled_sample_data_has_expected_count() -> None:
    # Sanity check against this repo's real bundled sample data directory.
    from toolkit.config import get_settings

    connector = UnstructuredFileConnector(directory=get_settings().sample_unstructured_dir)
    doc_ids = connector.list_documents()
    assert "northbridge_incomplete_upload" in doc_ids
    assert "northbridge_kyc_procedure" in doc_ids
    assert len(doc_ids) == 5


def test_unstructured_file_connector_missing_directory_raises() -> None:
    with pytest.raises(ConnectorError):
        UnstructuredFileConnector(directory="/path/does/not/exist/at/all")
