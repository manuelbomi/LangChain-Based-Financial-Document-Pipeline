# Security Policy

This is a portfolio/demonstration repository, not a production system, but
it follows the security hygiene practices expected in a regulated
environment.

## Supported versions

This is a single-version demo project; only the `main` branch is supported.

## Dependency management

- Dependencies are declared in `pyproject.toml` with explicit minimum
  versions and a same-major-version upper bound (see `[project.dependencies]`)
  to get security patches without silently pulling in breaking major
  releases.
- `.github/workflows/ci.yml` runs on every push/PR and includes a package
  build check; adding a dependency-scanning step (`pip-audit` or GitHub
  Dependabot) is a natural next addition -- see README "Roadmap".
- The Docker image (`Dockerfile`) pins its base image tag and installs only
  runtime dependencies in the final stage (multi-stage build), minimizing
  the attack surface of the shipped image.

## Secrets handling

- No secrets are required to run this toolkit's default demo -- every
  connector is mocked, SQLite-backed, or reads local synthetic files.
- Configuration is loaded via `pydantic-settings` from environment
  variables / a local `.env` file (see `.env.example`). `.env` is
  git-ignored; never commit a populated `.env`.
- Structured logging (`toolkit/logging_utils.py`) deliberately allowlists
  which fields are emitted rather than dumping arbitrary objects, to avoid
  a future contributor accidentally logging raw document content, PII, or
  secrets.

## Running as non-root

The Docker image creates and switches to an unprivileged `appuser` before
the final `CMD` -- see `Dockerfile`.

## Reporting a vulnerability

This is a personal portfolio project. If you find an issue, please open a
GitHub issue describing it; there is no dedicated security contact or SLA.
