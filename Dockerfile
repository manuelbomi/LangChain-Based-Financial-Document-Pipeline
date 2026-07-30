# syntax=docker/dockerfile:1
#
# Multi-stage build for the Enterprise Document Pipeline Toolkit CLI.
#
# Stage 1 ("builder") installs the package + its dependencies into a
# virtualenv. Stage 2 copies only that virtualenv and the application code
# into a slim runtime image, dropping build tools (compilers, pip cache,
# wheel metadata) from the final image -- smaller image, smaller attack
# surface. The final image runs as a non-root user.

FROM python:3.11.9-slim-bookworm AS builder

WORKDIR /build

# Install into an isolated venv (rather than system site-packages) so the
# runtime stage can copy just this directory wholesale.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY toolkit ./toolkit
COPY README.md ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

FROM python:3.11.9-slim-bookworm AS runtime

# Create an unprivileged user/group up front -- the whole point of the
# multi-stage build is to hand this stage nothing that needs root to
# install, so we can drop to appuser immediately after copying artifacts.
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --shell /usr/sbin/nologin --create-home appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # toolkit.config's default data paths are computed relative to where
    # the `toolkit` package is installed (repo root in a dev checkout).
    # Inside this image the package lives under /opt/venv/lib/..., which is
    # NOT /app -- so without these overrides the container would look for
    # sample data in the wrong place. Pinning them here makes `docker run
    # <image> ...` work standalone with zero extra flags; docker-compose.yml
    # and the k8s manifests set the same three vars explicitly too (belt and
    # suspenders, and it's the pattern any real external volume mount needs).
    TOOLKIT_SAMPLE_UNSTRUCTURED_DIR=/app/data/sample_unstructured \
    TOOLKIT_SAMPLE_DB_PATH=/app/data/sample_bank.db \
    TOOLKIT_STATE_DIR=/app/data/state

WORKDIR /app
COPY --chown=appuser:appuser data ./data

USER appuser

# Default: run a health-check so `docker run` with no args gives an
# immediate, meaningful signal. Override the command to run `toolkit
# ingest --source ...` etc. -- see docker-compose.yml and deploy/k8s/.
ENTRYPOINT ["toolkit"]
CMD ["health-check"]
