"""
Enterprise Document Pipeline Toolkit
=====================================

A small, installable Python toolkit + CLI for building RAG-ready document
ingestion pipelines over financial-services data sources (core banking APIs,
relational databases, and unstructured file drops).

Architectural role of this package
-----------------------------------
``toolkit`` is the top-level namespace for the whole system. It is organized
into clearly separated layers so that each concern can be tested, replaced,
or extended independently:

- ``toolkit.connectors``  -> pulls raw documents from a source system
- ``toolkit.chunking``    -> splits document text into retrieval-sized chunks
- ``toolkit.metadata``    -> the canonical ``DocumentMetadata`` schema
- ``toolkit.validation``  -> data-quality gates + dead-letter routing
- ``toolkit.indexing``    -> delta/incremental indexing + staleness tracking
- ``toolkit.dag``         -> a tiny dependency-ordered pipeline runner
- ``toolkit.cli``         -> the Typer-based ``toolkit`` command line entrypoint

Nothing in this package makes real network calls by default -- connectors are
either mocked, backed by a bundled/auto-provisioned SQLite database, or read
from a local synthetic data directory. This keeps the whole toolkit runnable
fully offline, which matters for a reviewer cloning this repo without any
paid API keys.
"""

__version__ = "0.1.0"
