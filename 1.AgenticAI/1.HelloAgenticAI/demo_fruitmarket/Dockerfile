# syntax=docker/dockerfile:1.7
#
# Multi-stage Dockerfile for the fruit-market Chainlit demo.
#
# Build context = project root (1.AgenticAI/1.HelloAgenticAI/), set in
# infra/azure.yaml so the COPY paths resolve against framework/ and
# demo_fruitmarket/ at the repo root.
#
# Two stages: builder installs prod deps via uv into /app/.venv (no dev
# tools, no project install — source goes in via PYTHONPATH at runtime
# for fast iterative rebuilds). Runtime stage copies the venv + the two
# source packages (framework/ + demo_fruitmarket/) and runs Chainlit as
# a non-root user on port 8000.
#
# No secrets baked in. AZURE_OPENAI_ENDPOINT / AZURE_COSMOS_ENDPOINT are
# injected at runtime by the Container App's env vars (set from azd outputs
# in infra/modules/container-app.bicep). DefaultAzureCredential picks up
# the user-assigned managed identity at runtime via AZURE_CLIENT_ID.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.7

# ---------- builder ----------

FROM python:${PYTHON_VERSION}-slim AS builder
ARG UV_VERSION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Production deps only — dev tooling (ruff/mypy/pytest/pre-commit) is
# excluded. --no-install-project means we don't install the local
# packages here; we mount them via PYTHONPATH in the runtime stage so
# rebuilds after a source-only change skip the wheel-build step.
RUN uv sync --frozen --no-dev --no-install-project

# ---------- runtime ----------

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/app/.venv/bin:$PATH

# Non-root runtime user (Container App best practice, defence-in-depth).
RUN useradd --create-home --uid 1001 app
WORKDIR /app

# Copy the resolved venv from the builder. --chown=app:app ensures the
# non-root runtime user owns the file tree under /app — Chainlit's
# import-time setup calls FILES_DIRECTORY.mkdir() (= /app/.files) and
# without ownership the mkdir fails with PermissionError, crashing the
# container at startup.
COPY --chown=app:app --from=builder /app/.venv /app/.venv

# Copy the two source packages. Both must be on PYTHONPATH (= /app) so
# `from framework.* import ...` and `from demo_fruitmarket.* import ...`
# resolve cleanly.
COPY --chown=app:app framework/ framework/
COPY --chown=app:app demo_fruitmarket/ demo_fruitmarket/

USER app
EXPOSE 8000

# Chainlit doesn't serve /health out of the box, so we rely on the
# Container App's tcpSocket probe (configured in
# infra/modules/container-app.bicep) for health rather than a Docker
# HEALTHCHECK. Disabling explicitly so docker-built smoke tests don't
# show "unhealthy" while the app is actually up.
HEALTHCHECK NONE

# `--headless` so Chainlit doesn't try to open a browser inside the
# container; `--host 0.0.0.0` for Container App routing.
CMD ["chainlit", "run", "demo_fruitmarket/ui/app.py", \
     "--host", "0.0.0.0", "--port", "8000", "--headless"]
