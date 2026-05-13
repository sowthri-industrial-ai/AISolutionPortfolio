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

from fastapi import Body, FastAPI, HTTPException, Query
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
DEFAULT_SETPOINT_DICT = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/phase0a_setpoint_dictionary.json"
)
DEFAULT_PERTURBATION_INBOX = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/2.automation/stage2/perturbations_inbox"
)
DEFAULT_ADVISORY_STORE = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/2.automation/stage3/advisories.json"
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


# ----- Ontology response models (F2) -----


class OntologyRelationship(BaseModel):
    type: str
    target: str


class OntologyInboundRelationship(BaseModel):
    type: str
    source: str


class OntologyEntity(BaseModel):
    id: str
    type: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    subsystem: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)
    stages: Optional[list[dict[str, Any]]] = None
    normal_ranges: Optional[dict[str, dict[str, Any]]] = None
    relationships: list[OntologyRelationship] = Field(default_factory=list)


class OntologyEntityDetail(OntologyEntity):
    inbound_relationships: list[OntologyInboundRelationship] = Field(default_factory=list)
    tag_ids: list[str] = Field(default_factory=list)


class OntologyTagInfo(BaseModel):
    tag_id: str
    entity_id: str
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    property: str
    description: str
    unit: str
    category: str


class OntologyResolveHit(BaseModel):
    entity_id: str
    name: Optional[str] = None
    type: Optional[str] = None
    match_type: str
    matched_phrase: str
    score: int
    tag_ids: list[str]


class OntologyResolveResponse(BaseModel):
    term: str
    count: int
    results: list[OntologyResolveHit]


# ----- Setpoint write models (F3) -----


class SetpointWriteRequest(BaseModel):
    value: float
    requested_by: Optional[str] = Field(
        default="stage3_api",
        description="Free-form caller hint. Agent should set this to its tool/session ID.",
    )


class SetpointWriteResponse(BaseModel):
    request_id: str
    setpoint_id: str
    queued_value: float
    status: str  # "queued"
    enqueued_at: str
    note: str = (
        "Perturbation queued to Stage 2 inbox; applied at the next solve cycle "
        "boundary. Inspect <inbox_dir>/<request_id>.applied or .failed for the "
        "result."
    )


# ----- Advisory models (F3) -----


class AdvisoryCreateRequest(BaseModel):
    setpoint_id: str
    target_value: float
    rationale: str = Field(
        ...,
        description="Why this change is being recommended. Operator reads this when deciding to approve/reject.",
    )
    created_by: Optional[str] = Field(
        default="agent",
        description="Caller identifier. Agent sets this to its tool/session ID.",
    )


class AdvisoryApproveRequest(BaseModel):
    approved_by: Optional[str] = "operator"


class AdvisoryRejectRequest(BaseModel):
    rejected_by: Optional[str] = "operator"
    reason: Optional[str] = None


class Advisory(BaseModel):
    advisory_id: str
    setpoint_id: str
    target_value: float
    rationale: str
    state: str  # pending | approved | rejected
    created_at: str
    created_by: Optional[str] = None
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    rejected_at: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_reason: Optional[str] = None
    perturbation_request_id: Optional[str] = None


# ----- Module state (populated at startup) -----


class State:
    tag_dict_path: Path = Path(os.environ.get("TAG_DICT_PATH", DEFAULT_TAG_DICT))
    stage2_dir: Path = Path(os.environ.get("STAGE2_DIR", DEFAULT_STAGE2_DIR))
    setpoint_dict_path: Path = Path(
        os.environ.get("SETPOINT_DICT_PATH", DEFAULT_SETPOINT_DICT)
    )
    perturbation_inbox: Path = Path(
        os.environ.get("PERTURBATION_INBOX", DEFAULT_PERTURBATION_INBOX)
    )
    advisory_store_path: Path = Path(
        os.environ.get("ADVISORY_STORE_PATH", DEFAULT_ADVISORY_STORE)
    )
    tag_dict: dict[str, dict] = {}
    tag_list: list[dict] = []
    ontology: Any = None  # OntologyLoader instance, loaded in lifespan
    setpoint_catalog: Any = None  # SetpointCatalog (perturbations.py)
    inbox_writer: Any = None  # InboxWriter (perturbations.py)
    advisory_store: Any = None  # AdvisoryStore (advisories.py)


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


def _load_ontology() -> None:
    """Instantiate the F2 OntologyLoader. Local import keeps the ontology
    module loaded only when api.py is imported (not as a side effect of
    importing models)."""
    # Local import — ontology.py is sibling in 2.automation/stage3/
    from ontology import OntologyLoader

    State.ontology = OntologyLoader()
    print(
        f"[stage3] ontology loaded: "
        f"{len(State.ontology.entities)} entities, "
        f"{State.ontology.tag_mapping['tag_count']} tag mappings",
        flush=True,
    )


def _load_setpoints_and_inbox() -> None:
    """Load setpoint catalog + create inbox writer (F3 perturbation infra).
    Local import so importing api.py without the F3 module on path stays cheap."""
    from perturbations import SetpointCatalog, InboxWriter

    if not State.setpoint_dict_path.is_file():
        raise RuntimeError(f"setpoint dict not found: {State.setpoint_dict_path}")
    State.setpoint_catalog = SetpointCatalog(State.setpoint_dict_path)
    State.inbox_writer = InboxWriter(State.perturbation_inbox)
    print(
        f"[stage3] setpoint catalog loaded: "
        f"{len(State.setpoint_catalog.by_id)} entries "
        f"({len(State.setpoint_catalog.list_perturbable())} perturbable); "
        f"inbox at {State.perturbation_inbox}",
        flush=True,
    )


def _load_advisory_store() -> None:
    """Instantiate the AdvisoryStore — depends on setpoint_catalog + inbox_writer
    already being loaded. Persists to JSON, survives restart."""
    from advisories import AdvisoryStore

    State.advisory_store = AdvisoryStore(
        State.advisory_store_path,
        State.setpoint_catalog,
        State.inbox_writer,
    )
    print(
        f"[stage3] advisory store loaded: "
        f"{len(State.advisory_store.advisories)} total "
        f"({State.advisory_store.pending_count()} pending); "
        f"path={State.advisory_store_path}",
        flush=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_tag_dict()
    _load_ontology()
    _load_setpoints_and_inbox()
    _load_advisory_store()
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


# ----- Ontology endpoints (F2) -----


@app.get("/ontology/schema", tags=["ontology"])
def ontology_schema() -> dict[str, Any]:
    """The raw entity-type + relationship-type schema. Static after startup.
    Returned as a dict (response_model omitted) so the rich nested schema
    structure renders verbatim without intermediate Pydantic flattening."""
    return State.ontology.schema


@app.get(
    "/ontology/entities",
    response_model=list[OntologyEntity],
    tags=["ontology"],
)
def ontology_entities() -> list[OntologyEntity]:
    """All 26 ontology entities (23 Phase 0a sim objects + 3 aggregators:
    Refinery + 2 Subsystems). Filter by `type` field client-side."""
    return [OntologyEntity(**e) for e in State.ontology.entities.values()]


@app.get(
    "/ontology/entities/{entity_id}",
    response_model=OntologyEntityDetail,
    tags=["ontology"],
)
def ontology_entity(entity_id: str) -> OntologyEntityDetail:
    """One entity + its outbound `relationships`, the reverse-direction
    `inbound_relationships`, and the `tag_ids` mapped to it from
    tag_mapping.json. 404 if unknown."""
    entity = State.ontology.get_entity(entity_id)
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "entity_not_found", "entity_id": entity_id},
        )
    rels = State.ontology.get_relationships(entity_id)
    tag_ids = State.ontology.get_tags_for_entity(entity_id)
    return OntologyEntityDetail(
        **entity,
        inbound_relationships=[
            OntologyInboundRelationship(**r) for r in rels["inbound"]
        ],
        tag_ids=tag_ids,
    )


@app.get(
    "/ontology/tags/{tag_id}",
    response_model=OntologyTagInfo,
    tags=["ontology"],
)
def ontology_tag(tag_id: str) -> OntologyTagInfo:
    """Reverse lookup: which entity owns this tag? Augments the tag
    mapping with the owning entity's name and type."""
    info = State.ontology.get_tag_info(tag_id)
    if info is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "tag_not_found", "tag_id": tag_id},
        )
    e = State.ontology.get_entity(info["entity_id"])
    return OntologyTagInfo(
        tag_id=info["tag_id"],
        entity_id=info["entity_id"],
        entity_name=e.get("name") if e else None,
        entity_type=e.get("type") if e else None,
        property=info["property"],
        description=info["description"],
        unit=info["unit"],
        category=info["category"],
    )


@app.get(
    "/ontology/resolve",
    response_model=OntologyResolveResponse,
    tags=["ontology"],
)
def ontology_resolve(
    term: str = Query(
        ...,
        min_length=1,
        description="Natural-language term to resolve. Two-tier match: exact "
                    "alias hit (score 100) → substring fallback (score scaled by "
                    "length ratio, capped 95).",
    ),
) -> OntologyResolveResponse:
    """Natural-language term → ranked list of {entity, tag_ids}. Demo:
    `?term=condenser%20duty` → ES-CONDENSER_DUTY with EnergyFlow tag."""
    hits = State.ontology.resolve_term(term)
    return OntologyResolveResponse(
        term=term,
        count=len(hits),
        results=[OntologyResolveHit(**h) for h in hits],
    )


# ----- Setpoint write endpoint (F3) -----


@app.post(
    "/setpoints/{setpoint_id}/value",
    response_model=SetpointWriteResponse,
    tags=["setpoints"],
)
def setpoints_write(setpoint_id: str, req: SetpointWriteRequest) -> SetpointWriteResponse:
    """Queue a perturbation request to Stage 2's inbox. Stage 2 applies at
    the next solve cycle boundary; the next snapshot will reflect the new
    value.

    Validation gate (Q3 default (b) — perturbable list + bounds check):
      - 404 if setpoint_id is unknown
      - 422 if setpoint is non-perturbable
      - 422 if value is out of the dictionary's bounds.low / bounds.high
      - 422 if value is non-numeric (bool, string, null)

    Inspect the result via the inbox: <inbox>/<request_id>.applied or
    .failed will appear within ~1 cycle (~30 s).
    """
    ok, err, entry = State.setpoint_catalog.validate_write(setpoint_id, req.value)
    if not ok:
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "setpoint_not_found", "setpoint_id": setpoint_id},
            )
        raise HTTPException(
            status_code=422,
            detail={
                "error": "validation_failed",
                "setpoint_id": setpoint_id,
                "reason": err,
                "perturbable": entry.get("perturbable"),
                "bounds": entry.get("bounds"),
                "bounds_kind": entry.get("bounds_kind"),
                "current_value": entry.get("current_value"),
            },
        )

    inbox_request = {
        "setpoint_id": setpoint_id,
        "owner_tag": entry["owner_tag"],
        "owner_type": entry["owner_type"],
        "property_key": entry["property_key"],
        "value": req.value,
        "requested_by": req.requested_by,
    }
    request_id = State.inbox_writer.enqueue(inbox_request)
    return SetpointWriteResponse(
        request_id=request_id,
        setpoint_id=setpoint_id,
        queued_value=req.value,
        status="queued",
        enqueued_at=inbox_request["enqueued_at"],
    )


# ----- Advisory endpoints (F3) -----


@app.post(
    "/advisories",
    response_model=Advisory,
    status_code=201,
    tags=["advisories"],
)
def advisory_create(req: AdvisoryCreateRequest) -> Advisory:
    """Create a pending advisory. Same setpoint validation gate as
    POST /setpoints/{id}/value — 404 on unknown setpoint, 422 on
    non-perturbable / out-of-bounds / non-numeric."""
    adv, err, entry = State.advisory_store.create(
        req.setpoint_id, req.target_value, req.rationale, req.created_by or "agent"
    )
    if adv is None:
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "setpoint_not_found", "setpoint_id": req.setpoint_id},
            )
        raise HTTPException(
            status_code=422,
            detail={
                "error": "validation_failed",
                "setpoint_id": req.setpoint_id,
                "reason": err,
                "perturbable": entry.get("perturbable"),
                "bounds": entry.get("bounds"),
                "bounds_kind": entry.get("bounds_kind"),
                "current_value": entry.get("current_value"),
            },
        )
    return Advisory(**adv)


@app.get(
    "/advisories",
    response_model=list[Advisory],
    tags=["advisories"],
)
def advisory_list(
    state: Optional[str] = Query(
        None,
        pattern="^(pending|approved|rejected)$",
        description="Filter by state. Omit to list all.",
    ),
) -> list[Advisory]:
    """List advisories, newest-first. Optional filter by state."""
    return [Advisory(**a) for a in State.advisory_store.list(state)]


@app.post(
    "/advisories/{advisory_id}/approve",
    response_model=Advisory,
    tags=["advisories"],
)
def advisory_approve(
    advisory_id: str,
    req: AdvisoryApproveRequest = Body(default_factory=AdvisoryApproveRequest),
) -> Advisory:
    """Approve a pending advisory: enqueues a perturbation request into
    Stage 2's inbox using the same atomic-file protocol as direct
    setpoint writes. Returns the updated advisory with
    `perturbation_request_id` set.

    Status codes:
      201 success (returns full Advisory with state="approved")
      404 advisory_not_found
      409 already approved or rejected
      422 setpoint validation failed at approval time (rare; catalog
          changed between create and approve)
    """
    adv, err, status_code = State.advisory_store.approve(
        advisory_id, req.approved_by or "operator"
    )
    if adv is None:
        raise HTTPException(
            status_code=status_code or 500,
            detail={"error": err, "advisory_id": advisory_id},
        )
    return Advisory(**adv)


@app.post(
    "/advisories/{advisory_id}/reject",
    response_model=Advisory,
    tags=["advisories"],
)
def advisory_reject(
    advisory_id: str,
    req: AdvisoryRejectRequest = Body(default_factory=AdvisoryRejectRequest),
) -> Advisory:
    """Reject a pending advisory; no perturbation enqueued. Same 404/409
    semantics as approve."""
    adv, err, status_code = State.advisory_store.reject(
        advisory_id, req.rejected_by or "operator", req.reason
    )
    if adv is None:
        raise HTTPException(
            status_code=status_code or 500,
            detail={"error": err, "advisory_id": advisory_id},
        )
    return Advisory(**adv)


# ----- Entry point -----

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
