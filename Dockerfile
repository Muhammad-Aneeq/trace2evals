# Optional container for `docker compose up`. The primary install path is `uv tool install` / `pipx`.
#
# Build the SPA first (`make build`): this image copies the built assets rather than installing Node,
# which keeps it small and keeps the build reproducible from a single toolchain.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependency metadata first, so a source-only change does not reinstall the world.
COPY pyproject.toml README.md ./
COPY backend/src/t2e/__init__.py backend/src/t2e/__init__.py

RUN pip install --no-cache-dir hatchling && pip install --no-cache-dir .

# Now the real source, including the built SPA at backend/src/t2e/web (see the note above).
COPY backend/ backend/
COPY scripts/ scripts/
RUN pip install --no-cache-dir --no-deps .

# Labels and traces live on a mounted volume, never inside the image.
RUN mkdir -p /data
ENV T2E_DB_PATH=/data/t2e.db

# Runs unprivileged: this tool has no reason to be root.
RUN useradd --create-home --uid 10001 t2e && chown -R t2e:t2e /app /data
USER t2e

EXPOSE 8765

# No telemetry, no outbound calls. The only network surface is this port.
CMD ["t2e", "label", "--serve", "--no-browser", "--host", "0.0.0.0", "--port", "8765"]
