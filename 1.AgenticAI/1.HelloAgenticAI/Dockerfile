# syntax=docker/dockerfile:1.7
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
# Production deps only — dev tooling (ruff/mypy/pytest/pre-commit) is excluded.
# --no-install-project means we don't install the local package; we mount the
# source via PYTHONPATH at runtime instead, which keeps the image rebuild fast
# during iterative development.
RUN uv sync --frozen --no-dev --no-install-project

# ---------- runtime ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/app/.venv/bin:$PATH

# Non-root runtime user
RUN useradd --create-home --uid 1001 app
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY framework/ framework/
# Phase 2 deletes placeholder.py and replaces it with the real agent entrypoint.
COPY placeholder.py ./

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "placeholder:app", "--host", "0.0.0.0", "--port", "8000"]
