# Contributing

This is a personal portfolio project, but it's built to normal open-source
hygiene. If you'd like to extend it:

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
make install
```

## Before opening a PR

```bash
make lint        # ruff
make typecheck    # mypy
make test         # pytest, with coverage report
```

All three run in CI (`.github/workflows/ci.yml`) on every push/PR, along
with a package build check and a Docker build check.

## Conventions

- Layered architecture: connectors / chunking / validation / indexing / cli
  are separate packages under `toolkit/` -- avoid adding cross-layer
  imports that break that separation (e.g. `toolkit.chunking` should never
  import from `toolkit.cli`).
- Every non-trivial function/class gets a docstring explaining its role;
  inline comments should explain *why*, not restate *what* the code does.
- New connectors implement `toolkit.connectors.base.SourceConnector` and
  register in `toolkit.connectors.CONNECTOR_REGISTRY`.
- New chunking strategies implement `toolkit.chunking.base.Chunker` and
  register in `toolkit.chunking.CHUNKER_REGISTRY`. By convention every
  concrete `Chunker.__init__` accepts `chunk_size` as its first argument
  (other tuning knobs are strategy-specific) -- `toolkit.pipeline` relies on
  this convention to instantiate any registered strategy uniformly.
- Keep the default demo fully offline -- no new dependency should require
  network access or a paid API key to run `make test` or `make run`.
- No real employer, bank, or person names anywhere in this repository. Use
  the fictional "Northbridge Financial Group" for any example data.
