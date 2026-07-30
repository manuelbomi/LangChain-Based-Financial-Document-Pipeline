"""
Recursive character-based chunking (LangChain's RecursiveCharacterTextSplitter).

Why this strategy exists
-------------------------
This is the default, general-purpose splitter: fast, dependency-light, and a
reasonable baseline for most prose documents. It splits on a priority list
of separators (paragraph -> line -> sentence -> word) and only falls back to
a hard character cut when nothing else fits, which tends to keep sentences
intact better than a naive fixed-width splitter. See the tradeoff table in
README.md for how this compares to the token-aware and semantic strategies.
"""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from toolkit.chunking.base import Chunk, Chunker

STRATEGY_NAME = "recursive"


class RecursiveChunker(Chunker):
    """Thin adapter over LangChain's RecursiveCharacterTextSplitter."""

    strategy_name = STRATEGY_NAME

    def __init__(self, chunk_size: int = 400, chunk_overlap: int = 50) -> None:
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def split(self, doc_id: str, text: str) -> list[Chunk]:
        pieces = self._splitter.split_text(text)
        return [
            Chunk(doc_id=doc_id, chunk_index=i, content=piece, strategy=self.strategy_name)
            for i, piece in enumerate(pieces)
        ]
