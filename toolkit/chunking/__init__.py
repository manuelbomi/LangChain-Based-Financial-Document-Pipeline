"""
Chunking strategies: split document text into retrieval-sized pieces behind
a single ``Chunker`` interface.

Three strategies ship with the toolkit, each with different latency /
coherence / cost tradeoffs -- see the comparison table in README.md:

- ``recursive``   -- LangChain's RecursiveCharacterTextSplitter (fast, generic)
- ``token-aware`` -- splits on an approximate token count, better for
                     matching an embedding model's context window
- ``semantic``    -- groups sentences using a deterministic, offline
                      "mock embedding" cosine-similarity heuristic; a stand-in
                      for a real embedding-based semantic chunker that would
                      call out to an embeddings API in production
"""

from toolkit.chunking.base import Chunk, Chunker
from toolkit.chunking.recursive import RecursiveChunker
from toolkit.chunking.semantic import SemanticChunker
from toolkit.chunking.token_aware import TokenAwareChunker

#: Registry used by the CLI / pipeline to resolve a strategy name to a class.
CHUNKER_REGISTRY: dict[str, type[Chunker]] = {
    "recursive": RecursiveChunker,
    "token-aware": TokenAwareChunker,
    "semantic": SemanticChunker,
}

__all__ = [
    "Chunk",
    "Chunker",
    "RecursiveChunker",
    "TokenAwareChunker",
    "SemanticChunker",
    "CHUNKER_REGISTRY",
]
