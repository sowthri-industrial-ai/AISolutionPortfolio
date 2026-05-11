#!/usr/bin/env python3
"""Stage 3 — FastAPI REST over Stage 2 snapshot JSONL files.

Read-only HTTP access to the live + historical refinery digital twin tag set.
Same data source as Stage 5 (Event Hubs producer): the Stage 2 streamer's
hour-bucket JSONL files. No DWSIM connection, no cloud, no database.

Setup (one-time):
    arch -x86_64 ../.venv-x86/bin/pip install fastapi 'uvicorn[standard]' pyyaml

Run (from 2.automation/stage3/):
    arch -x86_64 ../.venv-x86/bin/uvicorn api:app --host 0.0.0.0 --port 8080 --reload

Or via Python directly (uses uvicorn under the hood):
    arch -x86_64 ../.venv-x86/bin/python api.py

Config via env vars (defaults assume the standard project layout):
    TAG_DICT_PATH  path to phase0a_tag_dictionary.json
    STAGE2_DIR     path to 4.snapshots/stage2/
    HOST           bind host (default 0.0.0.0)
    PORT           bind port (default 8080)

OpenAPI 3.0 spec auto-generated at /openapi.json; static export to
docs/api/openapi.yaml via the export_openapi.py helper in this dir.
"""

from __future__ import annotations

import gzip
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

# ----- Constants & config -----

DEFAULT_TAG_DICT = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/phase0a_tag_dictionary.json"
)
DEFAULT_STAGE2_DIR = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/4.snapshots/stage2"
)
EXPECTED_TAG_COUNT = 1550

# Hour-bucket file naming (mirrors Stage 2 streamer).
HOUR_RE = re.compile(r"^stream_(\d{4}-\d{2}-\d{2}T\d{2})\.jsonl(\.gz)?$")
HOUR_FMT = "%Y-%m-%dT%H"

# Range query limits — briefing AC: max 10 000 per request.
RANGE_DEFAULT_LIMIT = 1000
RANGE_MAX_LIMIT = 10000


# ----- Pydantic models (response schemas drive OpenAPI) -----


class Snapshot(BaseModel):
    timestamp: str
    cycle: int
    solved: bool
    solve_time_s: Optional[float] = None
    cycle_duration_s: Optional[float] = None
    tag_count: int = 0
    errors: list[str] = Field(default_factory=list)
    tags: dict[str, Any] = Field(default_factory=dict)
    errors_truncated: Optional[bool] = None
    total_error_count: Optional[int] = None


class TagEntry(BaseModel):
    tag_id: str
    owner_tag: str
    owner_type: str
    phase: Optional[str] = None
    property_key: str
    description: Optional[str] = None
    unit_si: Optional[str] = None
    category: str
    subsystem: Optional[str] = None
    property_package: Optional[str] = None
    static_composition: Optional[bool] = None
    composition_meaningful: Optional[bool] = None
    current_value: Any = None


class TagValueResponse(BaseModel):
    tag_id: str
    timestamp: str
    cycle: int
    value: Any = None


class TagHistoryPoint(BaseModel):
    timestamp: str
    value: Any = None


class TagHistoryResponse(BaseModel):
    tag_id: str
    count: int
    points: list[TagHistoryPoint]


class HealthResponse(BaseModel):
    status: str
    stage2_active: bool
    latest_cycle: Optional[int] = None
    active_file: Optional[str] = None


class RangeResponse(BaseModel):
    count: int
    truncated: bool
    snapshots: list[Snapshot]


# ----- Module state (populated at startup) -----


class State:
    tag_dict_path: Path = Path(os.environ.get("TAG_DICT_PATH", DEFAULT_TAG_DICT))
    stage2_dir: Path = Path(os.environ.get("STAGE2_DIR", DEFAULT_STAGE2_DIR))
    tag_dict: dict[str, dict] = {}
    tag_list: list[dict] = []


def _load_tag_dict() -> None:
    if not State.tag_dict_path.is_file():
        raise RuntimeError(f"tag dict not found: {State.tag_dict_path}")
    with open(State.tag_dict_path) as f:
        State.tag_list = json.load(f)
    State.tag_dict = {t["tag_id"]: t for t in State.tag_list}
    if len(State.tag_list) != EXPECTED_TAG_COUNT:
        # Loud warning at startup; API still works for whatever count loaded.
        print(
            f"[stage3] WARN: tag dict has {len(State.tag_list)} entries, "
            f"expected {EXPECTED_TAG_COUNT}",
            flush=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_tag_dict()
    yield


app = FastAPI(
    title="Refinery Digital Twin — REST",
    description=(
        "Read-only HTTP access to live + historical DWSIM snapshots from the "
        "Stage 2 streamer. No DWSIM connection, no cloud — just the JSONL "
        "stream the streamer writes to local disk."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ----- Helpers -----


def parse_iso(s: str) -> Optional[datetime]:
    """Parse ISO 8601 with optional Z suffix. Returns None on failure."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, AttributeError, TypeError):
        return None


def find_active_jsonl() -> Optional[Path]:
    """Newest stream_*.jsonl (NOT .gz). Filename sort = chronological."""
    candidates = sorted(State.stage2_dir.glob("stream_*.jsonl"))
    return candidates[-1] if candidates else None


def read_last_snapshot(path: Path) -> Optional[dict]:
    """Last non-empty JSON line of a jsonl file. Returns dict or None."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if not data:
        return None
    for raw in reversed(data.split(b"\n")):
        line = raw.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def list_hour_files(since: datetime, until: datetime) -> list[tuple[Path, bool]]:
    """Files (path, is_gz) whose hour bucket overlaps [since, until]. Oldest first.
    Hour-bucket pruning: skip files whose hour is fully outside the request range."""
    out: list[tuple[Path, bool]] = []
    for p in sorted(State.stage2_dir.glob("stream_*.jsonl*")):
        m = HOUR_RE.match(p.name)
        if not m:
            continue
        try:
            file_hour = datetime.strptime(m.group(1), HOUR_FMT).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        file_hour_end = file_hour + timedelta(hours=1)
        if file_hour_end <= since or file_hour > until:
            continue
        out.append((p, m.group(2) == ".gz"))
    return out


def iter_snapshots_in_range(since: datetime, until: datetime, limit: int):
    """Yield snapshots in [since, until], ascending. Stops after `limit`."""
    yielded = 0
    for path, is_gz in list_hour_files(since, until):
        opener = gzip.open if is_gz else open
        try:
            with opener(path, "rt", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        snap = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = parse_iso(snap.get("timestamp", ""))
                    if ts is None or ts < since or ts > until:
                        continue
                    yield snap
                    yielded += 1
                    if yielded >= limit:
                        return
        except OSError:
            # File rotated/gzipped mid-iteration — skip and continue.
            continue


# ----- Endpoints -----


@app.get("/healthz", response_model=HealthResponse, tags=["meta"])
def healthz() -> HealthResponse:
    active = find_active_jsonl()
    if active is None:
        return HealthResponse(status="ok", stage2_active=False)
    snap = read_last_snapshot(active)
    return HealthResponse(
        status="ok",
        stage2_active=snap is not None,
        latest_cycle=snap.get("cycle") if snap else None,
        active_file=active.name,
    )


@app.get("/snapshots/latest", response_model=Snapshot, tags=["snapshots"])
def snapshots_latest() -> Snapshot:
    active = find_active_jsonl()
    if active is None:
        raise HTTPException(status_code=503, detail={"error": "streamer_not_running"})
    snap = read_last_snapshot(active)
    if snap is None:
        raise HTTPException(
            status_code=503, detail={"error": "no_snapshots_in_active_file"}
        )
    return Snapshot(**snap)


@app.get("/snapshots/range", response_model=RangeResponse, tags=["snapshots"])
def snapshots_range(
    since: str = Query(..., description="ISO 8601 lower bound (inclusive)"),
    until: str = Query(..., description="ISO 8601 upper bound (inclusive)"),
    limit: int = Query(RANGE_DEFAULT_LIMIT, ge=1, le=RANGE_MAX_LIMIT),
) -> RangeResponse:
    since_dt = parse_iso(since)
    until_dt = parse_iso(until)
    if since_dt is None or until_dt is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "bad_timestamp",
                "hint": "use ISO 8601, e.g. 2026-05-10T00:00:00Z",
            },
        )
    if since_dt > until_dt:
        raise HTTPException(status_code=422, detail={"error": "since_after_until"})
    snaps = list(iter_snapshots_in_range(since_dt, until_dt, limit))
    return RangeResponse(
        count=len(snaps),
        truncated=len(snaps) == limit,
        snapshots=[Snapshot(**s) for s in snaps],
    )


@app.get("/tags", response_model=list[TagEntry], tags=["tags"])
def tags() -> list[TagEntry]:
    return [TagEntry(**t) for t in State.tag_list]


@app.get("/tags/{tag_id}", response_model=TagEntry, tags=["tags"])
def tags_get(tag_id: str) -> TagEntry:
    entry = State.tag_dict.get(tag_id)
    if entry is None:
        raise HTTPException(
            status_code=404, detail={"error": "tag_not_found", "tag_id": tag_id}
        )
    return TagEntry(**entry)


@app.get("/tags/{tag_id}/value", response_model=TagValueResponse, tags=["tags"])
def tags_value(tag_id: str) -> TagValueResponse:
    if tag_id not in State.tag_dict:
        raise HTTPException(
            status_code=404, detail={"error": "tag_not_found", "tag_id": tag_id}
        )
    active = find_active_jsonl()
    if active is None:
        raise HTTPException(status_code=503, detail={"error": "streamer_not_running"})
    snap = read_last_snapshot(active)
    if snap is None:
        raise HTTPException(
            status_code=503, detail={"error": "no_snapshots_in_active_file"}
        )
    return TagValueResponse(
        tag_id=tag_id,
        timestamp=snap.get("timestamp", ""),
        cycle=snap.get("cycle", -1),
        value=snap.get("tags", {}).get(tag_id),
    )


@app.get("/tags/{tag_id}/history", response_model=TagHistoryResponse, tags=["tags"])
def tags_history(
    tag_id: str,
    since: str = Query(..., description="ISO 8601 lower bound (inclusive)"),
    until: str = Query(..., description="ISO 8601 upper bound (inclusive)"),
    limit: int = Query(RANGE_DEFAULT_LIMIT, ge=1, le=RANGE_MAX_LIMIT),
) -> TagHistoryResponse:
    if tag_id not in State.tag_dict:
        raise HTTPException(
            status_code=404, detail={"error": "tag_not_found", "tag_id": tag_id}
        )
    since_dt = parse_iso(since)
    until_dt = parse_iso(until)
    if since_dt is None or until_dt is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "bad_timestamp",
                "hint": "use ISO 8601, e.g. 2026-05-10T00:00:00Z",
            },
        )
    if since_dt > until_dt:
        raise HTTPException(status_code=422, detail={"error": "since_after_until"})
    points: list[TagHistoryPoint] = []
    for snap in iter_snapshots_in_range(since_dt, until_dt, limit):
        points.append(
            TagHistoryPoint(
                timestamp=snap.get("timestamp", ""),
                value=snap.get("tags", {}).get(tag_id),
            )
        )
    return TagHistoryResponse(tag_id=tag_id, count=len(points), points=points)


# ----- Entry point -----

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
