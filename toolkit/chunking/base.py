"""
Common interface every chunking strategy implements.

Architectural role
-------------------
The pipeline (and the CLI) only ever depend on this ``Chunker`` protocol, so
swapping the chunking strategy is a one-line config change (``--strategy``),
never a code change in the pipeline orchestration layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field


class Chunk(BaseModel):
    """One retrieval-sized piece of a document, ready for embedding/indexing."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    chunk_index: int = Field(..., ge=0)
    content: str
    strategy: str


class Chunker(ABC):
    """Contract for splitting a document's text into ``Chunk`` objects."""

    #: Short, stable identifier stored on each produced ``Chunk``.
    strategy_name: str = "unknown"

    @abstractmethod
    def split(self, doc_id: str, text: str) -> list[Chunk]:
        """Split ``text`` into ordered chunks for ``doc_id``."""
        raise NotImplementedError
