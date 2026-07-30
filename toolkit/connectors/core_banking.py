"""
Mock connector for a fictional core-banking REST API.

Architectural role
-------------------
Simulates fetching account/product disclosure documents from an internal
core-banking service without making any real network call -- everything is
served from an in-memory fixture. The retry/backoff/timeout machinery here
is written exactly as it would be for a *real* HTTP connector, so this class
doubles as the reference pattern for wiring up ``tenacity`` retries on any
future connector that does real I/O.

All example content references the fictional "Northbridge Financial Group"
brand only -- see README.md for the disclosure that this is synthetic data.
"""

from __future__ import annotations

import random
import time

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from toolkit.connectors.base import ConnectorError, RawDocument, SourceConnector
from toolkit.logging_utils import get_logger

logger = get_logger(__name__)

SOURCE_NAME = "core-banking-api"

# In-memory "REST responses" -- stands in for what would otherwise be JSON
# payloads returned by an internal core-banking service. Kept deliberately
# small and readable; each entry is one synthetic customer-facing document.
_MOCK_API_RESPONSES: dict[str, dict] = {
    "cb-doc-001": {
        "title": "Northbridge Financial Group -- Personal Checking Account Terms",
        "body": (
            "Northbridge Financial Group Personal Checking Account Terms and Conditions. "
            "This account is offered by Northbridge Financial Group, a fictional bank used "
            "solely for demonstration purposes. Monthly maintenance fee is waived with a "
            "minimum daily balance of $1,500. Overdraft protection is available and may be "
            "linked to a Northbridge Financial Group savings account. Interest, where "
            "applicable, is compounded daily and credited monthly."
        ),
        "effective_date": "2026-01-01",
        "classification": "internal",
    },
    "cb-doc-002": {
        "title": "Northbridge Financial Group -- Wire Transfer Policy",
        "body": (
            "Northbridge Financial Group Wire Transfer Policy. Domestic wire transfers "
            "initiated before 4:00 PM ET are processed same business day. International "
            "wires require additional compliance screening under Northbridge Financial "
            "Group's sanctions and AML program before release. Wire limits vary by customer "
            "tier and can be adjusted through a Northbridge Financial Group relationship "
            "manager."
        ),
        "effective_date": "2026-02-15",
        "classification": "confidential",
    },
    "cb-doc-003": {
        "title": "Northbridge Financial Group -- Small Business Loan Product Sheet",
        "body": (
            "Northbridge Financial Group Small Business Loan Product Sheet. Fixed and "
            "variable rate options are available for qualifying small businesses. Loan "
            "amounts range from $25,000 to $500,000 with terms up to 10 years. All "
            "applications are subject to Northbridge Financial Group underwriting "
            "guidelines and credit review."
        ),
        "effective_date": "2026-03-01",
        "classification": "public",
    },
}


class _TransientAPIError(Exception):
    """Simulated transient failure from the mock core-banking API."""


class CoreBankingAPIConnector(SourceConnector):
    """Reads mocked core-banking REST responses from memory.

    ``failure_rate`` lets tests/demos exercise the retry path deterministically
    by seeding ``random.Random`` -- production code would instead see real
    transient network errors here (timeouts, 5xx, connection resets).
    """

    source_name = SOURCE_NAME

    def __init__(self, failure_rate: float = 0.0, seed: int | None = 42, timeout_seconds: float = 5.0) -> None:
        self._failure_rate = failure_rate
        self._rng = random.Random(seed)
        self._timeout_seconds = timeout_seconds

    def list_documents(self) -> list[str]:
        return sorted(_MOCK_API_RESPONSES.keys())

    @retry(
        # Exponential backoff with jitter, capped attempts -- standard
        # resilience pattern for any real network-bound connector so a
        # single blip doesn't fail an entire ingestion run.
        retry=retry_if_exception_type(_TransientAPIError),
        wait=wait_random_exponential(multiplier=0.05, max=1.0),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _call_api(self, doc_id: str) -> dict:
        """Simulated HTTP GET with a timeout budget and injected flakiness."""
        start = time.monotonic()
        if self._rng.random() < self._failure_rate:
            logger.warning(
                "core_banking_transient_error",
                extra={"fields": {"doc_id": doc_id, "source": SOURCE_NAME}},
            )
            raise _TransientAPIError(f"simulated transient failure fetching {doc_id}")

        if doc_id not in _MOCK_API_RESPONSES:
            raise ConnectorError(f"document not found in core-banking API: {doc_id}")

        elapsed = time.monotonic() - start
        if elapsed > self._timeout_seconds:  # pragma: no cover - defensive only
            raise ConnectorError(f"core-banking API call exceeded timeout budget for {doc_id}")
        return _MOCK_API_RESPONSES[doc_id]

    def fetch(self, doc_id: str) -> RawDocument:
        try:
            payload = self._call_api(doc_id)
        except _TransientAPIError as exc:
            # Retries exhausted -- surface as a ConnectorError the pipeline
            # can catch and route around, rather than an opaque tenacity
            # RetryError leaking a library-specific exception type upward.
            raise ConnectorError(f"core-banking API unavailable for {doc_id} after retries") from exc

        return RawDocument(
            doc_id=doc_id,
            title=payload["title"],
            content=payload["body"],
            source_system=SOURCE_NAME,
            raw_metadata={
                "data_classification": payload["classification"],
                "effective_date": payload["effective_date"],
                "retention_tag": "standard-7y",
            },
        )
