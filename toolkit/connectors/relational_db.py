"""
SQLite-backed connector standing in for a relational "document/notes" table
that a bank's internal systems might expose (e.g. relationship-manager call
notes, product disclosures stored in a CMS-backed table).

Architectural role
-------------------
Demonstrates a connector over a real (if embedded) database rather than an
in-memory fixture, including connection handling and a bounded retry for
transient lock errors (``sqlite3.OperationalError``), which is the same
shape of resilience code you'd want for a networked RDBMS connector (Oracle,
Postgres) in production.

The sample database is auto-provisioned on first use so `pip install -e .`
+ a single CLI command works with zero setup steps -- see ``_ensure_seeded``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from toolkit.connectors.base import ConnectorError, RawDocument, SourceConnector
from toolkit.logging_utils import get_logger

logger = get_logger(__name__)

SOURCE_NAME = "relational-db"

# Synthetic seed rows -- fictional Northbridge Financial Group relationship
# manager notes / disclosures stored in a relational table.
_SEED_ROWS = [
    (
        "rdb-doc-001",
        "Northbridge Financial Group -- Q1 Relationship Review Note",
        "Relationship manager note for Northbridge Financial Group commercial client "
        "portfolio review. Client requested increased line of credit; documentation "
        "package routed to underwriting for Northbridge Financial Group approval.",
        "2026-01-10",
        "confidential",
    ),
    (
        "rdb-doc-002",
        "Northbridge Financial Group -- Mortgage Rate Disclosure",
        "Standard Northbridge Financial Group mortgage rate disclosure for 30-year "
        "fixed products. Rates shown are illustrative and subject to change without "
        "notice per Northbridge Financial Group pricing policy.",
        "2026-02-01",
        "public",
    ),
    (
        "rdb-doc-003",
        "Northbridge Financial Group -- Fraud Case Summary",
        "Internal fraud case summary for Northbridge Financial Group card services. "
        "Case involved a disputed transaction later confirmed as unauthorized; account "
        "was reissued per Northbridge Financial Group fraud response procedure.",
        "2026-03-05",
        "restricted",
    ),
    (
        "rdb-doc-004",
        "Northbridge Financial Group -- Branch Hours Update",
        "Northbridge Financial Group branch network hours update for the upcoming "
        "holiday schedule, applicable to all Northbridge Financial Group retail "
        "locations.",
        "2026-03-20",
        "public",
    ),
]


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_seeded(db_path: Path) -> None:
    """Create schema + seed data if the sample DB doesn't exist yet.

    Keeping this idempotent (CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE)
    means the connector is safe to construct repeatedly (e.g. once per CLI
    invocation) without duplicating rows.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                effective_date TEXT NOT NULL,
                classification TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT OR IGNORE INTO documents (doc_id, title, body, effective_date, classification) "
            "VALUES (?, ?, ?, ?, ?)",
            _SEED_ROWS,
        )
        conn.commit()


class RelationalDBConnector(SourceConnector):
    """Reads document rows from a bundled/auto-provisioned SQLite database."""

    source_name = SOURCE_NAME

    def __init__(self, db_path: Path | str | None = None) -> None:
        from toolkit.config import get_settings

        self._db_path = Path(db_path) if db_path is not None else get_settings().sample_db_path
        _ensure_seeded(self._db_path)

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = _connect(self._db_path)
        try:
            yield conn.cursor()
        finally:
            conn.close()

    @retry(
        retry=retry_if_exception_type(sqlite3.OperationalError),
        wait=wait_random_exponential(multiplier=0.05, max=1.0),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def list_documents(self) -> list[str]:
        try:
            with self._cursor() as cur:
                cur.execute("SELECT doc_id FROM documents ORDER BY doc_id")
                return [row["doc_id"] for row in cur.fetchall()]
        except sqlite3.DatabaseError as exc:
            raise ConnectorError(f"failed listing documents from relational DB: {exc}") from exc

    @retry(
        retry=retry_if_exception_type(sqlite3.OperationalError),
        wait=wait_random_exponential(multiplier=0.05, max=1.0),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def fetch(self, doc_id: str) -> RawDocument:
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
                row = cur.fetchone()
        except sqlite3.DatabaseError as exc:
            raise ConnectorError(f"failed fetching {doc_id} from relational DB: {exc}") from exc

        if row is None:
            raise ConnectorError(f"document not found in relational DB: {doc_id}")

        return RawDocument(
            doc_id=doc_id,
            title=row["title"],
            content=row["body"],
            source_system=SOURCE_NAME,
            raw_metadata={
                "data_classification": row["classification"],
                "effective_date": row["effective_date"],
                "retention_tag": "standard-7y",
            },
        )
