# Governance & Guardrails

This toolkit is a portfolio demonstration, but it is built the way a
regulated-industry (banking) data pipeline should be built: governance is
not bolted on afterward, it is enforced at the schema and validation layer.
This document summarizes the controls implemented and where to find them.

## 1. Mandatory data classification

Every document that reaches the index carries a `data_classification` tag
(`public` / `internal` / `confidential` / `restricted`) as a **required**
field on `toolkit.metadata.DocumentMetadata` -- there is no default value.
A document without a valid classification cannot be constructed into a
`DocumentMetadata` object and is rejected by validation (see below).

In a production deployment, `data_classification` is the hook downstream
systems would use to decide, e.g., which documents are eligible for a
lower-trust or third-party-hosted vector index vs. an on-prem-only one, or
which require additional encryption-at-rest controls. That routing logic is
out of scope for this toolkit, but the tag is designed to carry it.

## 2. Audit log of every pipeline run

Every invocation of `toolkit ingest` / `toolkit reindex` appends one JSON
line to `data/state/audit_log.jsonl` (`toolkit.pipeline.AuditLog`) recording:

- `run_id`, `source`, `strategy`, start/finish timestamps
- documents seen, newly indexed, reindexed (changed), skipped (unchanged),
  and failed validation
- which document IDs were PII-flagged and which are currently stale

This is intentionally separate from the structured application logs
(`toolkit.logging_utils`) -- the audit log is a durable, easy-to-query
record of pipeline outcomes for compliance review, independent of wherever
day-to-day logs are shipped/rotated.

## 3. PII pattern flags are surfaced, never silently dropped

`toolkit.validation.DataQualityValidator` scans document content for
SSN-shaped and account-number-shaped patterns. **Flagged documents are not
rejected, redacted, or silently indexed** -- the flag is attached to the
validation outcome, logged as a structured warning, and rolled up into the
run's audit-log summary (`pii_flagged_doc_ids`). Silently stripping the
content would hide a data-handling problem from the humans who need to
decide what to do about it; silently indexing it without flagging would be
a governance failure. Deciding the downstream policy (route to manual
review, mask before indexing, etc.) is left to the calling application --
this toolkit's job is to guarantee the signal is never lost.

These are illustrative regex patterns, not a production-grade PII/NER
scanner -- see `toolkit/validation.py` for the exact patterns and their
documented limitations.

## 4. Dead-letter routing, with reasons

Documents that fail validation -- missing required governance metadata,
unparseable/invalid metadata values, or duplicate content checksum within a
batch -- are routed to a dead-letter store
(`data/state/dead_letter.jsonl`, `toolkit.validation.DeadLetterStore`)
rather than being dropped or crashing the run. Every entry records the
`doc_id`, `source_system`, a human-readable `reason`, the `run_id`, and a
timestamp. Inspect it with:

```bash
toolkit dead-letter list
```

## 5. Retention tagging

Every document carries a `retention_tag` (e.g. `standard-7y`) sourced from
the connector's raw metadata. This toolkit does not implement retention
*enforcement* (deletion on expiry) -- that requires integration with a
system of record for retention schedules -- but the tag is captured at
ingestion time so it travels with every chunk into the index
(`toolkit.pipeline.EnrichedChunk`).

## 6. Staleness detection

`toolkit.indexing.DeltaIndex.stale_doc_ids()` flags any document not
re-seen by a connector within a configurable freshness SLA
(`TOOLKIT_FRESHNESS_SLA_HOURS`, default 24h). This surfaces silently-broken
ingestion (a scheduled job stopped running, a source system stopped
returning a document) as an operational signal rather than letting a RAG
system quietly serve increasingly out-of-date answers.

## 7. Fictional data only

All example content in this repository references "Northbridge Financial
Group", an invented bank used solely for demonstration. No real customer,
employee, or institutional data appears anywhere in this repository. Example
SSN- and account-number-shaped strings used to exercise PII detection are
synthetic test fixtures, not real identifiers.
