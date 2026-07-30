"""
Structured (JSON) logging with per-run correlation IDs.

Architectural role
-------------------
Production observability starts with logs that are machine-parseable and
correlate every line back to a single pipeline execution. This module:

- Emits one JSON object per log line (easy to ship to any log aggregator /
  SIEM commonly used at regulated financial institutions).
- Attaches a ``run_id`` (a UUID4 generated once per pipeline invocation) to
  every log record via a ``contextvars``-backed filter, so all stages of one
  run can be correlated without threading an argument through every call.
- NEVER logs secrets or raw PII: callers must pass already-redacted/derived
  values (e.g. a checksum, not raw document content) into log fields. See
  ``toolkit.validation`` for how PII is *flagged* rather than logged.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

# A ContextVar so the current run's correlation ID is implicitly available to
# every log call on the same async/sync call stack without global mutable
# state and without passing it through every function signature.
_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="unset")


def new_run_id() -> str:
    """Generate and install a fresh correlation ID for a pipeline run."""
    run_id = uuid.uuid4().hex[:12]
    _run_id_var.set(run_id)
    return run_id


def current_run_id() -> str:
    """Return the correlation ID for the currently executing pipeline run."""
    return _run_id_var.get()


class _RunIdFilter(logging.Filter):
    """Injects the active run_id into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = current_run_id()
        return True


class _JsonFormatter(logging.Formatter):
    """Renders each LogRecord as a single-line JSON object.

    Deliberately whitelists which fields are emitted rather than dumping
    ``record.__dict__`` wholesale -- an allowlist is the safer default for a
    logging layer that must never leak secrets/PII accidentally attached to
    a record by a future contributor.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": getattr(record, "run_id", "unset"),
        }
        # Allow callers to attach structured extra fields via `extra={"fields": {...}}`.
        extra_fields = getattr(record, "fields", None)
        if extra_fields:
            payload.update(extra_fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Idempotently configure the root logger for the whole process.

    Called once from the CLI entrypoint. Tests call it too (harmless to
    call multiple times -- handlers are cleared first).
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(_RunIdFilter())
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s run=%(run_id)s %(name)s: %(message)s"))
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Standard logger accessor -- module-level ``logging.getLogger`` wrapper for consistency."""
    return logging.getLogger(name)
