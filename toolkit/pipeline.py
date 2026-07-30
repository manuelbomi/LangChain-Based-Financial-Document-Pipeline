"""
Wires connectors, validation, chunking, metadata enrichment, and delta
indexing together into one ingest pipeline, executed via the tiny DAG
runner in ``toolkit.dag``.

Architectural role
-------------------
This module is the only place that knows the full stage order:

    connect -> validate -> chunk -> enrich_metadata -> index
                   |
                   +--> dead-letter store (validation failures branch off here)

Every other module (connectors, validation, chunking, indexing) is
independently testable in isolation; this module composes them and is what
the CLI calls. Each stage also gets a lightweight tracing span (see
``_span``) and the whole run is summarized to a JSONL audit log -- required
governance artifact: "which documents were processed/skipped/failed, when".
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from toolkit.chunking import CHUNKER_REGISTRY
from toolkit.chunking.base import Chunk
from toolkit.config import Settings
from toolkit.connectors import CONNECTOR_REGISTRY
from toolkit.dag import DagRunner
from toolkit.indexing import DeltaIndex
from toolkit.logging_utils import get_logger, new_run_id
from toolkit.metadata import DocumentMetadata, DocumentRecord, utcnow
from toolkit.validation import DataQualityValidator, DeadLetterStore, ValidationOutcome

logger = get_logger(__name__)


class EnrichedChunk:
    """A chunk paired with its parent document's governance metadata.

    This is the payload shape a real vector-store writer would consume: the
    chunk text plus everything an index/retrieval layer needs to enforce
    classification-aware access control and staleness at query time. Kept
    as a plain, JSON-serializable object (not a pydantic model) to avoid
    over-engineering a type that only exists transiently within one run.
    """

    def __init__(self, chunk: Chunk, metadata: DocumentMetadata, pii_flags: list[str]) -> None:
        self.chunk = chunk
        self.metadata = metadata
        self.pii_flags = pii_flags

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.chunk.doc_id,
            "chunk_index": self.chunk.chunk_index,
            "content": self.chunk.content,
            "strategy": self.chunk.strategy,
            "source_system": self.metadata.source_system,
            "data_classification": self.metadata.data_classification.value,
            "effective_date": self.metadata.effective_date.isoformat(),
            "retention_tag": self.metadata.retention_tag,
            "content_checksum": self.metadata.content_checksum,
            "pii_flags": self.pii_flags,
        }


@contextmanager
def _span(stage: str) -> Iterator[None]:
    """Minimal tracing span: logs stage start/duration/status.

    Stands in for an OpenTelemetry span (`tracer.start_as_current_span`) --
    same shape (name, duration, success/failure), zero extra dependency.
    Swapping this for a real OTel span is a contained change; see the
    Observability section of README.md.
    """
    start = time.monotonic()
    logger.info("stage_start", extra={"fields": {"stage": stage}})
    try:
        yield
    except Exception:
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        logger.error("stage_failed", extra={"fields": {"stage": stage, "duration_ms": duration_ms}})
        raise
    else:
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        logger.info("stage_complete", extra={"fields": {"stage": stage, "duration_ms": duration_ms}})


@dataclass
class PipelineSummary:
    """Audit-log-friendly summary of one pipeline run."""

    run_id: str
    source: str
    strategy: str
    docs_seen: int = 0
    docs_indexed: int = 0
    docs_reindexed: int = 0
    docs_skipped_unchanged: int = 0
    docs_failed_validation: int = 0
    pii_flagged_doc_ids: list[str] = field(default_factory=list)
    stale_doc_ids: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source": self.source,
            "strategy": self.strategy,
            "docs_seen": self.docs_seen,
            "docs_indexed": self.docs_indexed,
            "docs_reindexed": self.docs_reindexed,
            "docs_skipped_unchanged": self.docs_skipped_unchanged,
            "docs_failed_validation": self.docs_failed_validation,
            "pii_flagged_doc_ids": self.pii_flagged_doc_ids,
            "stale_doc_ids": self.stale_doc_ids,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class AuditLog:
    """Append-only JSONL audit trail of pipeline run summaries.

    Governance requirement: every run must leave a record of how many
    documents were processed / skipped / failed, independent of the
    structured application logs (which may be shipped elsewhere / rotated
    on a different schedule).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, summary: PipelineSummary) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary.to_dict()) + "\n")

    def list_entries(self) -> list[dict]:
        if not self._path.exists():
            return []
        return [json.loads(line) for line in self._path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_pipeline(
    settings: Settings,
    source: str,
    strategy: str = "recursive",
    since: date | None = None,
) -> PipelineSummary:
    """Build and execute the full ingest DAG for one source connector.

    This is the function the CLI's `ingest` and `reindex` commands both
    call -- reindexing is simply re-running the same pipeline, relying on
    the delta index to make unchanged documents cheap. ``since``, when
    given, scopes reindexing to documents whose business ``effective_date``
    is on/after that date -- everything else is left untouched (not even
    touched for freshness purposes), matching `toolkit reindex --since`.
    """
    if source not in CONNECTOR_REGISTRY:
        raise ValueError(f"unknown source '{source}'; choices: {sorted(CONNECTOR_REGISTRY)}")
    if strategy not in CHUNKER_REGISTRY:
        raise ValueError(f"unknown chunking strategy '{strategy}'; choices: {sorted(CHUNKER_REGISTRY)}")

    settings.ensure_state_dir()
    run_id = new_run_id()
    summary = PipelineSummary(run_id=run_id, source=source, strategy=strategy, started_at=utcnow().isoformat())

    connector = CONNECTOR_REGISTRY[source]()
    chunker_cls = CHUNKER_REGISTRY[strategy]
    # Every concrete Chunker accepts `chunk_size` as its first constructor
    # argument, but the ABC itself declares no __init__ (each strategy has
    # different remaining tuning knobs -- chunk_overlap vs.
    # similarity_threshold) so mypy can't verify this call against the
    # `type[Chunker]` base type. Safe in practice: enforced by convention
    # and by the chunking unit tests, documented in CONTRIBUTING.md.
    chunker = chunker_cls(chunk_size=settings.chunk_size)  # type: ignore[call-arg]
    dead_letter = DeadLetterStore(settings.dead_letter_path())
    validator = DataQualityValidator(dead_letter, run_id=run_id)
    index = DeltaIndex(settings.index_state_path(), freshness_sla_hours=settings.freshness_sla_hours)

    # --- Stage functions -------------------------------------------------
    # Each is a plain function of the shared DAG context so it can also be
    # unit-tested directly without going through the DagRunner if desired.

    def stage_connect(ctx: dict[str, Any]) -> list:
        with _span("connect"):
            return connector.fetch_all()

    def stage_validate(ctx: dict[str, Any]) -> list[ValidationOutcome]:
        with _span("validate"):
            outcomes = [validator.validate(raw) for raw in ctx["connect"]]
            summary.docs_seen = len(outcomes)
            summary.docs_failed_validation = sum(1 for o in outcomes if o.rejected)
            return outcomes

    def stage_chunk(ctx: dict[str, Any]) -> list[dict[str, Any]]:
        """Chunk only documents that are new/changed per the delta index.

        Evaluating (but not yet persisting) the delta-index decision here
        -- rather than in the `index` stage -- is what lets us skip the
        expensive chunking step entirely for unchanged documents.
        """
        with _span("chunk"):
            results = []
            for outcome in ctx["validate"]:
                if outcome.rejected or outcome.document is None:
                    continue
                document: DocumentRecord = outcome.document
                if since is not None and document.metadata.effective_date < since:
                    continue
                action = index.evaluate(document)
                chunks = [] if action == "unchanged" else chunker.split(document.doc_id, document.content)
                results.append(
                    {"document": document, "pii_flags": outcome.pii_flags, "action": action, "chunks": chunks}
                )
            return results

    def stage_enrich_metadata(ctx: dict[str, Any]) -> list[dict[str, Any]]:
        """Attach each document's governance metadata onto its chunks."""
        with _span("enrich_metadata"):
            enriched = []
            for item in ctx["chunk"]:
                document: DocumentRecord = item["document"]
                enriched_chunks = [
                    EnrichedChunk(chunk=c, metadata=document.metadata, pii_flags=item["pii_flags"])
                    for c in item["chunks"]
                ]
                enriched.append({**item, "enriched_chunks": enriched_chunks})
            return enriched

    def stage_index(ctx: dict[str, Any]) -> list[dict[str, Any]]:
        """Persist delta-index state (this is where state actually mutates)."""
        with _span("index"):
            for item in ctx["enrich_metadata"]:
                document: DocumentRecord = item["document"]
                action = item["action"]
                if item["pii_flags"]:
                    summary.pii_flagged_doc_ids.append(document.doc_id)
                if action == "unchanged":
                    index.touch_unchanged(document)
                    summary.docs_skipped_unchanged += 1
                else:
                    index.record_processed(document, chunk_count=len(item["enriched_chunks"]))
                    if action == "new":
                        summary.docs_indexed += 1
                    else:
                        summary.docs_reindexed += 1
            return ctx["enrich_metadata"]

    dag = DagRunner()
    dag.add_stage("connect", stage_connect)
    dag.add_stage("validate", stage_validate, depends_on=["connect"])
    dag.add_stage("chunk", stage_chunk, depends_on=["validate"])
    dag.add_stage("enrich_metadata", stage_enrich_metadata, depends_on=["chunk"])
    dag.add_stage("index", stage_index, depends_on=["enrich_metadata"])
    dag.run()

    summary.stale_doc_ids = index.stale_doc_ids()
    summary.finished_at = utcnow().isoformat()

    AuditLog(settings.audit_log_path()).record(summary)
    logger.info("pipeline_run_complete", extra={"fields": summary.to_dict()})
    return summary
