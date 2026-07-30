"""
Approximate token-aware chunking, sized by word count instead of characters.

Why this strategy exists
-------------------------
Embedding models and LLM context windows are budgeted in *tokens*, not
characters, so a character-based splitter can silently over/under-fill a
chunk relative to the model's real limit. A fully faithful implementation
would tokenize with the target model's actual tokenizer (e.g. ``tiktoken``);
this toolkit intentionally avoids that dependency because most tokenizer
libraries fetch their vocabulary/merge files over the network on first use,
which would break this repo's "fully offline by default" requirement.

Instead, we approximate: whitespace-delimited "words" are used as a stable,
offline proxy for tokens (a reasonable rule of thumb is ~0.75 tokens per
word for English prose). This keeps the strategy deterministic, dependency-
free, and good enough to demonstrate the token-budgeting *pattern* -- README
calls out explicitly that a production system should swap in a real
tokenizer via the same ``Chunker`` interface.
"""

from __future__ import annotations

import re

from toolkit.chunking.base import Chunk, Chunker

STRATEGY_NAME = "token-aware"

_WORD_RE = re.compile(r"\S+")


class TokenAwareChunker(Chunker):
    """Splits text into chunks of approximately ``chunk_size`` "tokens" (words)."""

    strategy_name = STRATEGY_NAME

    def __init__(self, chunk_size: int = 100, chunk_overlap: int = 15) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def split(self, doc_id: str, text: str) -> list[Chunk]:
        # Track (word, start_offset, end_offset) so we can reconstruct chunk
        # text as an exact substring of the original document rather than
        # re-joining tokens with a single space (which would lose original
        # whitespace/newline formatting).
        matches = list(_WORD_RE.finditer(text))
        if not matches:
            return []

        chunks: list[Chunk] = []
        step = self._chunk_size - self._chunk_overlap
        start_word = 0
        chunk_index = 0
        while start_word < len(matches):
            end_word = min(start_word + self._chunk_size, len(matches))
            span_start = matches[start_word].start()
            span_end = matches[end_word - 1].end()
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    chunk_index=chunk_index,
                    content=text[span_start:span_end],
                    strategy=self.strategy_name,
                )
            )
            chunk_index += 1
            if end_word == len(matches):
                break
            start_word += step
        return chunks
