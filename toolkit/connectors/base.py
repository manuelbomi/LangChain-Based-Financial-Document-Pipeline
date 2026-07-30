"""
Abstract base class every source connector must implement, plus the
``RawDocument`` contract connectors return.

Architectural role
-------------------
This is the seam between "how documents get into the pipeline" and
"everything the pipeline does with documents". Adding a new source system
(e.g. a document management system, a ticketing system) means writing one
new class here and registering it in ``toolkit.connectors.CONNECTOR_REGISTRY``
-- nothing downstream changes.

Why ``RawDocument`` and not the strict ``DocumentMetadata`` straight away?
Real source systems -- especially unstructured file drops -- do not
guarantee complete, well-typed metadata. A connector's job is to faithfully
represent what it found, including gaps; deciding whether those gaps are
fatal is ``toolkit.validation``'s job, not the connector's. This keeps
connectors simple (no validation logic duplicated in each one) and gives the
validator a single, uniform place to reject/dead-letter bad documents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConnectorError(Exception):
    """Raised when a connector cannot reach or read its source after retries."""


class RawDocument(BaseModel):
    """Loosely-typed document as read directly from a source system.

    ``raw_metadata`` intentionally holds untyped strings (or is missing
    keys entirely) -- ``toolkit.validation.DataQualityValidator`` is
    responsible for parsing/validating it into a strict
    ``toolkit.metadata.DocumentMetadata``.
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(..., min_length=1)
    title: str = Field(default="")
    content: str = Field(default="")
    source_system: str = Field(..., min_length=1)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class SourceConnector(ABC):
    """Contract for pulling documents from one source system.

    Implementations are expected to be side-effect-free with respect to the
    rest of the pipeline: they only read from their source and return
    ``RawDocument`` objects (or raise ``ConnectorError`` for I/O failures --
    as opposed to data-quality problems, which are surfaced as incomplete
    ``raw_metadata`` for the validator to catch).
    """

    #: Short, stable identifier stored as RawDocument.source_system.
    source_name: str = "unknown-source"

    @abstractmethod
    def list_documents(self) -> list[str]:
        """Return the list of document IDs currently available at the source."""
        raise NotImplementedError

    @abstractmethod
    def fetch(self, doc_id: str) -> RawDocument:
        """Fetch a single document (content + raw metadata) by ID."""
        raise NotImplementedError

    def fetch_all(self) -> list[RawDocument]:
        """Convenience helper: list then fetch every document.

        Kept as a concrete method (not abstract) since every connector gets
        this behavior for free from ``list_documents``/``fetch`` -- avoids
        duplicating the loop in every subclass.
        """
        return [self.fetch(doc_id) for doc_id in self.list_documents()]
