#!/usr/bin/env python3
"""F3 Stage 3 MCP server — 9 tools over stdio transport.

Tool inventory (9 unique, two groupings; `list_advisories` belongs to both):

    Read (5):
      check_health, get_tag, get_setpoint, list_perturbables, list_advisories
    Perturb (1):
      perturb_setpoint
    Advisory (4):
      recommend_action, approve_advisory, reject_advisory, list_advisories

Architecture:
  - Mutations (perturb / advisory CRUD) ALWAYS proxy through Stage 3's
    FastAPI app at STAGE3_BASE_URL. Stage 3 owns the perturbation inbox
    and advisory store; the MCP server never writes to either directly.
  - Reads for live tag values + advisory listings ALSO proxy HTTP — they
    need the current Stage 2 snapshot which only Stage 3 sees.
  - Reads for setpoint catalog (get_setpoint, list_perturbables) load
    SetpointCatalog in-process from the same Phase 0a dictionary that
    Stage 3 loads. Two copies stay in sync because the dictionary is
    a read-only Phase 0a artifact, never mutated at runtime. This
    avoids a hot HTTP roundtrip on every catalog query from the agent.

Runtime / venv:
  - Lives in a separate venv at 2.automation/f3/.venv (Python 3.11) —
    the `mcp` SDK requires >=3.10. Stage 2's streamer keeps its
    `.venv-x86` (Python 3.9, x86_64) because DWSIM Mono is x86-only.
    The two processes run side by side and communicate only via files
    (the Stage 2 perturbation inbox) and HTTP (Stage 3 ↔ MCP server).

Install (one-time, from 2.automation/f3/):
    /opt/homebrew/bin/python3.11 -m venv .venv
    .venv/bin/pip install mcp httpx

Run (typically spawned by an MCP-aware client over stdio):
    .venv/bin/python mcp_server.py

Configuration via env vars:
    STAGE3_BASE_URL     default http://localhost:8080
    SETPOINT_DICT_PATH  default <repo>/3.probes/phase0a/phase0a_setpoint_dictionary.json
    MCP_HTTP_TIMEOUT    default 10.0 (seconds)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Project paths + sys.path wiring for in-process catalog import
# ---------------------------------------------------------------------------

# this file: <repo>/2.automation/f3/mcp_server.py
#   parents[0] = .../f3
#   parents[1] = .../2.automation
#   parents[2] = .../<repo root: 1.RefineryDigitalTwin>
_HERE = Path(__file__).resolve()
_AUTOMATION = _HERE.parents[1]
_PROJECT_ROOT = _HERE.parents[2]

# Make stage3/perturbations.py importable for in-process SetpointCatalog use.
sys.path.insert(0, str(_AUTOMATION / "stage3"))

from perturbations import SetpointCatalog  # noqa: E402  (after sys.path mutation)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STAGE3_BASE_URL = os.environ.get("STAGE3_BASE_URL", "http://localhost:8080")
SETPOINT_DICT_PATH = Path(
    os.environ.get(
        "SETPOINT_DICT_PATH",
        str(
            _PROJECT_ROOT
            / "3.probes"
            / "phase0a"
            / "phase0a_setpoint_dictionary.json"
        ),
    )
)
HTTP_TIMEOUT = float(os.environ.get("MCP_HTTP_TIMEOUT", "10.0"))


# ---------------------------------------------------------------------------
# Server + shared state
# ---------------------------------------------------------------------------

mcp = FastMCP("refinery-digital-twin")

# Load the setpoint catalog eagerly — if the dictionary is missing this is
# a fatal misconfiguration and we want it loud at startup, not on first call.
_catalog = SetpointCatalog(SETPOINT_DICT_PATH)

# httpx.AsyncClient is created lazily on the first awaited tool call so that
# tool registration + JSON schema generation doesn't depend on a running
# event loop. The client lives for the life of the process.
_client: Optional[httpx.AsyncClient] = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=STAGE3_BASE_URL, timeout=HTTP_TIMEOUT
        )
    return _client


def _http_error(resp: httpx.Response, op: str) -> dict[str, Any]:
    """Render an HTTP error response into a dict the agent can read. Tries
    JSON body first (FastAPI's `detail` payloads are always JSON); falls
    back to raw text."""
    try:
        body: Any = resp.json()
    except ValueError:
        body = resp.text
    return {
        "error": f"{op}_http_error",
        "status_code": resp.status_code,
        "detail": body,
    }


# ---------------------------------------------------------------------------
# Read tools (5)
# ---------------------------------------------------------------------------


@mcp.tool()
async def check_health() -> dict[str, Any]:
    """Check Stage 3 API health + the upstream Stage 2 streamer status.

    Use this as a first call before any read/write — if `stage2_active` is
    False, the digital twin isn't producing fresh data and tag reads will
    return whatever was in the last persisted snapshot.

    Returns:
        status: "ok" if the Stage 3 process is responding.
        stage2_active: True if a Stage 2 .jsonl is currently being written.
        latest_cycle: highest Stage 2 cycle number in the active snapshot.
        active_file: filesystem path to the current hour-bucket .jsonl.
    """
    client = await _get_client()
    resp = await client.get("/healthz")
    if resp.status_code != 200:
        return _http_error(resp, "check_health")
    return resp.json()


@mcp.tool()
async def get_tag(tag_id: str) -> dict[str, Any]:
    """Read the latest value for a single tag from the live Stage 2 snapshot.

    Tag IDs use the Phase 0a canonical scheme:
        <owner_prefix>-<NORMALIZED_OWNER_TAG>.<property_key>
    Examples:
        COL-DISTILLATION_COLUMN.RefluxRatio
        HC-THERMAL_OIL_HEATING.OutletTemperature
        PMP-THERMAL_OIL_PUMP.Efficiency

    Args:
        tag_id: canonical tag identifier.

    Returns:
        tag_id: echoed back.
        timestamp: ISO 8601 of the snapshot that produced this value.
        cycle: Stage 2 cycle number (monotonic int, increments per solve).
        value: live value (numeric / string / list / null).
    """
    client = await _get_client()
    resp = await client.get(f"/tags/{tag_id}/value")
    if resp.status_code == 404:
        return {"error": "tag_not_found", "tag_id": tag_id}
    if resp.status_code != 200:
        return _http_error(resp, "get_tag")
    return resp.json()


@mcp.tool()
def get_setpoint(setpoint_id: str) -> dict[str, Any]:
    """Look up a setpoint's catalog entry: bounds, perturbable flag,
    description, current_value (Phase 0a snapshot — not live).

    Read this BEFORE calling `perturb_setpoint` or `recommend_action` to
    confirm the setpoint is writable and pick a value within bounds. If
    `perturbable` is False, `non_perturbable_reason` explains why (e.g.
    DWSIM internal reset behaviour for Recycle.MaximumIterations).

    Args:
        setpoint_id: canonical setpoint identifier (same scheme as tag_id).

    Returns the full catalog entry, including:
        setpoint_id, owner_type, owner_tag, property_key
        bounds: {"low", "high"} or null
        bounds_kind: how the bounds were derived in Phase 0a
        perturbable: True if writable at runtime
        non_perturbable_reason: optional reason when perturbable=False
        description, unit_si, current_value, ...
    """
    entry = _catalog.get(setpoint_id)
    if entry is None:
        return {"error": "setpoint_not_found", "setpoint_id": setpoint_id}
    return entry


@mcp.tool()
def list_perturbables() -> list[dict[str, Any]]:
    """List every setpoint that is writable at runtime.

    A setpoint is perturbable iff:
      (1) Phase 0a marked it `perturbable: true` (numeric + has bounds), AND
      (2) it is not in stage3/perturbations.py's NON_PERTURBABLE_OVERRIDES
          catalog filter (which excludes entries DWSIM resets internally on
          each solve cycle — e.g. Recycle.MaximumIterations).

    Returns 24 entries as of catalog filter commit 97bc936.
    """
    return _catalog.list_perturbable()


@mcp.tool()
async def list_advisories(state: Optional[str] = None) -> list[dict[str, Any]]:
    """List advisories newest-first.

    Args:
        state: optional filter — "pending" | "approved" | "rejected".
               Omit (or pass None) to list all states.

    Returns a list of Advisory records:
        advisory_id, setpoint_id, target_value, rationale, state,
        created_at, created_by, approved_at/by, rejected_at/by/reason,
        perturbation_request_id (set once approved).
    """
    if state is not None and state not in ("pending", "approved", "rejected"):
        return [
            {
                "error": "invalid_state",
                "detail": (
                    f"state={state!r}; expected one of "
                    "pending|approved|rejected or omitted"
                ),
            }
        ]
    params: dict[str, str] = {}
    if state:
        params["state"] = state
    client = await _get_client()
    resp = await client.get("/advisories", params=params)
    if resp.status_code != 200:
        return [_http_error(resp, "list_advisories")]
    return resp.json()


# ---------------------------------------------------------------------------
# Perturb tool (1) — direct write (no advisory gate)
# ---------------------------------------------------------------------------


@mcp.tool()
async def perturb_setpoint(
    setpoint_id: str,
    value: float,
    requested_by: str = "mcp_agent",
) -> dict[str, Any]:
    """Queue a direct setpoint write to the digital twin. Validation gate:
    must be in the perturbable catalog AND within bounds.low / bounds.high.
    Use this when you have authority to act unilaterally; otherwise prefer
    `recommend_action` so the operator approves first.

    Stage 2 picks the request up at the next solve-cycle boundary (~30 s).
    Inspect the result by polling `get_tag` after a cycle or two; the new
    value should be reflected. The Stage 2 inbox also persists a
    `<request_id>.applied` or `.failed` file for forensics.

    Args:
        setpoint_id: canonical ID (from list_perturbables).
        value: numeric target (within bounds).
        requested_by: caller identity (your agent/session ID).

    Returns on success:
        request_id, setpoint_id, queued_value, status="queued",
        enqueued_at, note.

    Returns on failure:
        error: "setpoint_not_found" | "validation_failed" |
               "perturb_setpoint_http_error".
        detail: structured reason (bounds, perturbable flag, etc.).
    """
    client = await _get_client()
    resp = await client.post(
        f"/setpoints/{setpoint_id}/value",
        json={"value": value, "requested_by": requested_by},
    )
    if resp.status_code == 404:
        return {"error": "setpoint_not_found", "setpoint_id": setpoint_id}
    if resp.status_code == 422:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return {"error": "validation_failed", "detail": body}
    if resp.status_code not in (200, 201):
        return _http_error(resp, "perturb_setpoint")
    return resp.json()


# ---------------------------------------------------------------------------
# Advisory tools (4) — advisory mode: recommend → operator approves/rejects
# ---------------------------------------------------------------------------


@mcp.tool()
async def recommend_action(
    setpoint_id: str,
    target_value: float,
    rationale: str,
    created_by: str = "mcp_agent",
) -> dict[str, Any]:
    """Create a PENDING advisory. The operator approves or rejects via
    `approve_advisory` / `reject_advisory` before any digital twin write
    occurs. Same validation gate as `perturb_setpoint` (must be in
    perturbable catalog + within bounds).

    Use this in advisory mode — when the agent has read-and-recommend
    authority but not write authority. The rationale string is the
    operator's primary signal for approval; be explicit about the
    observation that triggered the recommendation, the expected effect,
    and any side-effects worth watching.

    Args:
        setpoint_id: canonical ID (from list_perturbables).
        target_value: numeric target (within bounds).
        rationale: free-form text explaining WHY this change is recommended.
        created_by: caller identity.

    Returns the new Advisory (state="pending", advisory_id assigned).
    """
    client = await _get_client()
    resp = await client.post(
        "/advisories",
        json={
            "setpoint_id": setpoint_id,
            "target_value": target_value,
            "rationale": rationale,
            "created_by": created_by,
        },
    )
    if resp.status_code == 404:
        return {"error": "setpoint_not_found", "setpoint_id": setpoint_id}
    if resp.status_code == 422:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return {"error": "validation_failed", "detail": body}
    if resp.status_code not in (200, 201):
        return _http_error(resp, "recommend_action")
    return resp.json()


@mcp.tool()
async def approve_advisory(
    advisory_id: str,
    approved_by: str = "operator",
) -> dict[str, Any]:
    """Approve a pending advisory. Enqueues a perturbation request to
    Stage 2's inbox using the same atomic-file protocol as
    `perturb_setpoint`; returns the updated advisory with
    `perturbation_request_id` set.

    Args:
        advisory_id: from a prior `recommend_action` call.
        approved_by: caller identity.

    Returns:
        Advisory with state="approved", perturbation_request_id, approved_at, ...

    Error returns:
        404: advisory_not_found
        409: already_resolved (advisory already approved or rejected)
        422: validation_failed (catalog changed between create and approve)
    """
    client = await _get_client()
    resp = await client.post(
        f"/advisories/{advisory_id}/approve",
        json={"approved_by": approved_by},
    )
    if resp.status_code == 404:
        return {"error": "advisory_not_found", "advisory_id": advisory_id}
    if resp.status_code == 409:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return {"error": "already_resolved", "detail": body}
    if resp.status_code == 422:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return {"error": "validation_failed", "detail": body}
    if resp.status_code not in (200, 201):
        return _http_error(resp, "approve_advisory")
    return resp.json()


@mcp.tool()
async def reject_advisory(
    advisory_id: str,
    rejected_by: str = "operator",
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Reject a pending advisory. No perturbation is enqueued; the advisory
    is closed with state="rejected" + the rejection reason recorded.

    Args:
        advisory_id: from a prior `recommend_action` call.
        rejected_by: caller identity.
        reason: optional explanation (shown in subsequent `list_advisories`
                output — useful for audit + agent self-learning).

    Returns the updated Advisory (state="rejected").

    Error returns:
        404: advisory_not_found
        409: already_resolved
    """
    client = await _get_client()
    resp = await client.post(
        f"/advisories/{advisory_id}/reject",
        json={"rejected_by": rejected_by, "reason": reason},
    )
    if resp.status_code == 404:
        return {"error": "advisory_not_found", "advisory_id": advisory_id}
    if resp.status_code == 409:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return {"error": "already_resolved", "detail": body}
    if resp.status_code not in (200, 201):
        return _http_error(resp, "reject_advisory")
    return resp.json()


# ---------------------------------------------------------------------------
# Entry point — stdio transport
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run("stdio")
