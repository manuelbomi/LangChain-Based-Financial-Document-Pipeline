"""Tests for chunking strategies: fixed sample document, expected boundaries."""

from __future__ import annotations

from toolkit.chunking.recursive import RecursiveChunker
from toolkit.chunking.semantic import MockEmbedder, SemanticChunker, _cosine_similarity
from toolkit.chunking.token_aware import TokenAwareChunker

SAMPLE_TEXT = (
    "Northbridge Financial Group offers personal checking accounts. "
    "Monthly fees are waived above a minimum balance. "
    "Overdraft protection can be linked to a savings account. "
    "Interest is compounded daily and credited monthly."
)


# --- RecursiveChunker ----------------------------------------------------


def test_recursive_chunker_produces_bounded_nonempty_chunks() -> None:
    chunker = RecursiveChunker(chunk_size=60, chunk_overlap=10)
    chunks = chunker.split("doc-1", SAMPLE_TEXT)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.content.strip() != ""
        # RecursiveCharacterTextSplitter may exceed chunk_size slightly when
        # a single "atomic" separator unit (e.g. one sentence) is longer
        # than chunk_size, but should stay in a sane multiple of it.
        assert len(chunk.content) <= 60 * 2
        assert chunk.strategy == "recursive"

    # Indices are sequential starting at 0.
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_recursive_chunker_single_chunk_when_text_fits() -> None:
    chunker = RecursiveChunker(chunk_size=1000, chunk_overlap=50)
    chunks = chunker.split("doc-1", SAMPLE_TEXT)
    assert len(chunks) == 1
    assert chunks[0].content == SAMPLE_TEXT


# --- TokenAwareChunker (fully deterministic, word-count based) -----------


def test_token_aware_chunker_exact_boundaries_on_fixed_short_text() -> None:
    text = "one two three four five six seven eight nine ten"
    chunker = TokenAwareChunker(chunk_size=4, chunk_overlap=1)
    chunks = chunker.split("doc-1", text)

    # 10 words, window=4, step=3 (size-overlap) -> windows start at word
    # indices 0, 3, 6; the window starting at 6 reaches the end of the text
    # (words[6:10]) so the loop stops there rather than emitting a trailing
    # single-word chunk.
    assert [c.content for c in chunks] == [
        "one two three four",
        "four five six seven",
        "seven eight nine ten",
    ]
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_token_aware_chunker_rejects_overlap_gte_size() -> None:
    import pytest

    with pytest.raises(ValueError):
        TokenAwareChunker(chunk_size=5, chunk_overlap=5)


def test_token_aware_chunker_empty_text_returns_no_chunks() -> None:
    chunker = TokenAwareChunker(chunk_size=10, chunk_overlap=2)
    assert chunker.split("doc-1", "   ") == []


# --- SemanticChunker (deterministic mock-embedding heuristic) ------------


def test_mock_embedder_is_deterministic() -> None:
    embedder = MockEmbedder()
    v1 = embedder.embed("Northbridge checking account overdraft")
    v2 = embedder.embed("Northbridge checking account overdraft")
    assert v1 == v2


def test_mock_embedder_similar_sentences_score_higher_than_unrelated() -> None:
    embedder = MockEmbedder()
    a = embedder.embed("checking account overdraft protection savings")
    b = embedder.embed("checking account overdraft protection linked savings")
    c = embedder.embed("quarterly press release community lending expansion")

    sim_related = _cosine_similarity(a, b)
    sim_unrelated = _cosine_similarity(a, c)
    assert sim_related > sim_unrelated


def test_semantic_chunker_produces_nonempty_ordered_chunks() -> None:
    chunker = SemanticChunker(chunk_size=200, similarity_threshold=0.15)
    chunks = chunker.split("doc-1", SAMPLE_TEXT)

    assert len(chunks) >= 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk.strategy == "semantic"
        assert chunk.content.strip() != ""

    # Reassembling chunk content should preserve every sentence of the
    # original (order-preserving, nothing dropped).
    reassembled = " ".join(c.content for c in chunks)
    assert "checking accounts" in reassembled
    assert "compounded daily" in reassembled


def test_semantic_chunker_forces_new_chunk_when_size_cap_exceeded() -> None:
    # A tiny chunk_size forces a new chunk per sentence regardless of
    # similarity, since every merge would exceed the cap.
    chunker = SemanticChunker(chunk_size=10, similarity_threshold=0.0)
    chunks = chunker.split("doc-1", SAMPLE_TEXT)
    sentence_count = SAMPLE_TEXT.count(". ") + 1
    assert len(chunks) == sentence_count
