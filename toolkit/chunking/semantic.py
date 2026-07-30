"""
"Semantic-ish" chunking: groups sentences using embedding-similarity, with a
deterministic offline mock embedder standing in for a real embeddings API.

Why this strategy exists
-------------------------
A true semantic chunker calls an embeddings model per sentence (or small
window) and cuts chunk boundaries where topical similarity drops -- this
tends to produce the most *coherent* chunks (each chunk is "about one
thing"), at the cost of an embedding call per sentence, which is the most
expensive and highest-latency of the three strategies here.

This toolkit must run fully offline with no paid API keys, so
``SemanticChunker`` is built around an ``EmbeddingProvider`` interface with a
single implementation, ``MockEmbedder``: a deterministic hashed
bag-of-words vector (no ML model, no network call, no randomness). It is
*not* a real semantic representation -- it is a stand-in that lets us
demonstrate the similarity-driven chunk-boundary algorithm end-to-end and
produce stable, testable output. Swapping in a real embeddings client (e.g.
an internal model-serving endpoint) means implementing one more
``EmbeddingProvider`` and passing it to ``SemanticChunker`` -- no change to
the boundary-detection algorithm itself.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from toolkit.chunking.base import Chunk, Chunker

STRATEGY_NAME = "semantic"

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]*", re.MULTILINE)
_EMBED_DIM = 32


class EmbeddingProvider(Protocol):
    """Anything that can turn text into a fixed-length vector."""

    def embed(self, text: str) -> list[float]: ...


class MockEmbedder:
    """Deterministic, offline, ML-free "embedding".

    Hashes each lowercased word into one of ``_EMBED_DIM`` buckets and
    accumulates a bag-of-words count vector, then L2-normalizes it. Two
    sentences sharing more vocabulary land closer together in cosine
    similarity -- a crude but deterministic and dependency-free proxy for
    semantic similarity, sufficient to demonstrate the chunking pattern in
    an offline demo.
    """

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * _EMBED_DIM
        words = re.findall(r"[a-zA-Z0-9]+", text.lower())
        for word in words:
            bucket = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16) % _EMBED_DIM
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))  # vectors are already L2-normalized


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


class SemanticChunker(Chunker):
    """Groups consecutive sentences while their embedding similarity stays high.

    Parameters
    ----------
    chunk_size:
        Soft cap (characters) on how large a chunk may grow before a new
        chunk is forced, regardless of similarity -- prevents unbounded
        chunks when a document is unusually topically consistent.
    similarity_threshold:
        Minimum cosine similarity between a candidate sentence and the
        running chunk's centroid required to merge it into the current
        chunk rather than starting a new one.
    embedder:
        Defaults to :class:`MockEmbedder` for offline operation; inject a
        real embeddings client here in production.
    """

    strategy_name = STRATEGY_NAME

    def __init__(
        self,
        chunk_size: int = 400,
        similarity_threshold: float = 0.15,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self._chunk_size = chunk_size
        self._similarity_threshold = similarity_threshold
        self._embedder = embedder or MockEmbedder()

    def split(self, doc_id: str, text: str) -> list[Chunk]:
        sentences = _split_sentences(text)
        if not sentences:
            return []

        chunks: list[Chunk] = []
        current_sentences: list[str] = [sentences[0]]
        current_centroid = self._embedder.embed(sentences[0])
        current_len = len(sentences[0])

        def flush() -> None:
            content = " ".join(current_sentences)
            chunks.append(
                Chunk(doc_id=doc_id, chunk_index=len(chunks), content=content, strategy=self.strategy_name)
            )

        for sentence in sentences[1:]:
            candidate_vec = self._embedder.embed(sentence)
            similarity = _cosine_similarity(current_centroid, candidate_vec)
            would_exceed_size = current_len + len(sentence) + 1 > self._chunk_size

            if similarity >= self._similarity_threshold and not would_exceed_size:
                current_sentences.append(sentence)
                current_len += len(sentence) + 1
                # Running centroid = simple average of member embeddings,
                # re-normalized -- keeps the comparison point representative
                # of the whole chunk rather than drifting toward whichever
                # sentence was embedded last.
                merged = [c + v for c, v in zip(current_centroid, candidate_vec, strict=False)]
                norm = math.sqrt(sum(x * x for x in merged)) or 1.0
                current_centroid = [x / norm for x in merged]
            else:
                flush()
                current_sentences = [sentence]
                current_centroid = candidate_vec
                current_len = len(sentence)

        flush()
        return chunks
