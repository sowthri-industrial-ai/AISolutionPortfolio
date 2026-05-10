"""Phase 1 placeholder app — proves the Container App + ACR + identity wiring.

Phase 2 replaces this with the real LangGraph + Chainlit entrypoint.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from framework import __version__ as framework_version

app = FastAPI(title="HelloAgenticAI placeholder", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "phase": 1,
        "framework_version": framework_version,
        "container_app": os.getenv("CONTAINER_APP_NAME", "local"),
        "revision": os.getenv("CONTAINER_APP_REVISION", "local"),
    }


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "HelloAgenticAI placeholder. See /health."}
