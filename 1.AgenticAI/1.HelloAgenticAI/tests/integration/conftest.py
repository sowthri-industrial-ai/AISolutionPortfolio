"""Integration-test conftest — auto-loads ``azd env get-values`` into ``os.environ``.

Lets ``pytest tests/integration/`` "just work" against the deployed dev
environment without the user having to manually source env values
beforehand. If ``azd`` isn't installed or no environment exists, the
fixture is a no-op and individual tests will skip via their own missing-
endpoint checks.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# tests/integration/conftest.py → ../../infra/
_INFRA_DIR = Path(__file__).resolve().parent.parent.parent / "infra"


def _read_azd_env() -> dict[str, str]:
    """Run ``azd env get-values`` from infra/ and parse the KEY="value" lines."""
    if not _INFRA_DIR.exists():
        return {}
    try:
        result = subprocess.run(
            ["azd", "env", "get-values"],
            cwd=str(_INFRA_DIR),
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {}
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, _, raw = line.partition("=")
        out[key.strip()] = raw.strip().strip('"')
    return out


@pytest.fixture(scope="session", autouse=True)
def _autoload_azd_env() -> None:
    """Populate ``os.environ`` with azd env values if not already set."""
    # If the user (or CI) already exported one of the canonical vars,
    # assume they meant to override and skip the auto-load entirely.
    if os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_COSMOS_ENDPOINT"):
        return
    for key, value in _read_azd_env().items():
        os.environ.setdefault(key, value)
