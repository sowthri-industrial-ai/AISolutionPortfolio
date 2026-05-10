# A2 Briefing — Stages 3 (REST API) + 4 (OPC-UA Server)

**Project:** Refinery Digital Twin · Local industrial protocol layers
**Issued by:** Architect chat
**Implementer:** Claude Code
**Operator:** Sowthri
**Status:** A1 closed → this briefing
**Branch:** `phase-4-protocols` (per portfolio convention)
**Estimated effort:** ~2.5 days Claude Code (~1 day Stage 3 + ~1.5 days Stage 4)

---

## Goal

Add two local industrial-protocol layers exposing the live DWSIM tag set:

1. **Stage 3 — REST API** (FastAPI on localhost:8080): HTTP/JSON access to current and historical snapshots, OpenAPI-documented, suitable for ad-hoc integrations, Power BI direct queries, and third-party consumers.

2. **Stage 4 — OPC-UA Server** (asyncua on opc.tcp://localhost:4840): industrial-protocol exposure of the 1550 tags as OPC-UA nodes, browse-able by any OPC-UA client (UaExpert, KEPServerEX, Ignition, etc.), supporting subscriptions for change notifications.

Both layers read from the **same Stage 2 JSONL files** as Stage 5's Event Hubs producer. Single writer (Stage 2 streamer), four readers (Stages 3, 4, 5, future). No cloud dependency for A2 — all local.

A2 does NOT add cloud, agentic AI, or web UI. Those are F2/F3/F5.

## Why this matters

After A2 lands, the streamer foundation supports the **standard industrial integration triad**:
- **HTTP/REST** (modern, universal): web apps, scripts, BI tools, Postman testing
- **OPC-UA** (industrial standard): SCADA systems, historians, MES integrations, OT engineers' default protocol
- **Event Hubs** (cloud-native, from A1): Fabric, Stream Analytics, third-party stream consumers

This addresses the "where's the OPC-UA layer?" question that industrial audiences (Aramco, SABIC, ADNOC, refining/petrochemical procurement teams) will ask — and earns industrial credibility before the AI/agent layers (F2/F3) ship.

Demo-time: still invisible (the demo UI shows Fabric dashboards, not REST or OPC-UA). But the *story* upgrades from "we built a streamer" to "we built a streamer with the protocols a real refinery would consume." Worth ~2.5 days for the industrial-domain audience.

## Inputs

| | Default | |
|---|---|---|
| Stage 2 streamer | running, producing JSONL at `4.snapshots/stage2/stream_*.jsonl` | source for both Stage 3 and Stage 4 |
| Tag dictionary | `3.probes/phase0a/phase0a_tag_dictionary.json` | 1550 entries, drives node hierarchy |
| Stage 5 producer | running (from A1) | not consumed by A2; runs alongside |
| Cycle interval | 30 s (inherited from Stage 2) | not touched |
| REST port | 8080 | `--port` flag, default 8080 |
| OPC-UA port | 4840 | OPC-UA standard port |
| Update poll | 5 s | how often Stage 4 checks for new JSONL lines |

## Required reading

1. `docs/DWSIM_KNOWLEDGE_BASE.md` — bug classes still apply (some)
2. `docs/STREAMING_PLAN.md` — Stages 3 + 4 expectations
3. `2.automation/stage2/streamer.py` — JSONL semantics, snapshot schema
4. `2.automation/stage5/producer.py` — tail-position pattern (similar approach for A2)
5. `3.probes/phase0a/phase0a_tag_dictionary.json` + `phase0a_findings.md` — tag structure and overrides
6. This briefing — the contract

## Toolchain

Same `.venv-x86` venv (no need for separate environment — keeps things simple).

**New dependencies:**
```bash
arch -x86_64 ../.venv-x86/bin/pip install fastapi uvicorn[standard] asyncua
```

- `fastapi` (~3 MB): web framework, OpenAPI auto-generation
- `uvicorn[standard]` (~5 MB): ASGI server, hot-reload support for dev
- `asyncua` (~2 MB): mature Python OPC-UA library (server + client)

All pure Python wheels; install in seconds.

## Project layout

```
2.AssetsAI/1.RefineryDigitalTwin/
├── 2.automation/
│   ├── stage1/, stage2/, stage5/        (read-only, prior stages)
│   ├── stage3/                          ← NEW
│   │   ├── api.py                       FastAPI server
│   │   └── README.md                    runtime + endpoint docs
│   └── stage4/                          ← NEW
│       ├── opcua_server.py              asyncua server
│       ├── node_hierarchy.py            tag-dict → OPC-UA tree builder
│       └── README.md                    runtime + browse docs
└── docs/
    └── api/
        ├── openapi.yaml                 generated from FastAPI; checked in for stable diffs
        └── opcua_browse_paths.md        sample browse paths for industrial clients
```

---

## Stage 3 — REST API (FastAPI)

### Behavior

**File:** `2.automation/stage3/api.py` (~250-350 lines)

**1. Bootstrap**
- Load `phase0a_tag_dictionary.json` once at startup
- Cache the active hour's JSONL filename (refreshed on each request via Stage 2's filesystem)
- No DWSIM connection — Stage 3 is read-only against JSONL files

**2. Endpoints**

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/healthz` | `{"status":"ok","stage2_active":true,"latest_cycle":N}` | Liveness probe |
| GET | `/snapshots/latest` | full latest snapshot (Stage 2 schema) | Reads tail of current hour file |
| GET | `/snapshots/range?since=ISO&until=ISO&limit=1000` | array of snapshots | Iterates current hour + closed `.gz` files; respects limit |
| GET | `/tags` | array of tag dictionary entries | Static, served from in-memory cache |
| GET | `/tags/{tag_id}` | single tag dictionary entry | 404 if not found |
| GET | `/tags/{tag_id}/value` | latest value for one tag | Latest snapshot, single tag extraction |
| GET | `/tags/{tag_id}/history?since=ISO&until=ISO` | time series for one tag | Same source as `/snapshots/range`, projection |
| GET | `/openapi.json` | OpenAPI 3.0 spec | Auto-generated by FastAPI |
| GET | `/docs` | Swagger UI | FastAPI default |
| GET | `/redoc` | ReDoc UI | FastAPI default |

**3. Historical access**
- For `/snapshots/range` and `/tags/{id}/history`:
  - Reads current hour `.jsonl` line by line, filtering by timestamp
  - Reads closed `.jsonl.gz` files (decompresses on-demand using `gzip` module)
  - Hour-bucket pruning: skip files whose hour is fully outside the requested range
  - Limit: max 10000 snapshots per request to avoid memory blowup
  - Sort: oldest first (timestamp ascending)

**4. Error handling**
- Stage 2 not running (no active hour file) → 503 Service Unavailable, `{"error":"streamer_not_running"}`
- Tag ID not in dictionary → 404 Not Found
- Range too large → 422 Unprocessable Entity, hint to narrow
- Malformed timestamp → 422 with format hint

**5. Run command**

```bash
cd 2.automation/stage3
arch -x86_64 ../.venv-x86/bin/uvicorn api:app --host 0.0.0.0 --port 8080 --reload
```

### Acceptance criteria — Stage 3

- [ ] `api.py` exists at `2.automation/stage3/api.py`
- [ ] `uvicorn api:app --port 8080` starts without errors
- [ ] `GET /healthz` returns 200 OK with non-null `latest_cycle` when Stage 2 is running
- [ ] `GET /snapshots/latest` returns the most recent snapshot, schema-valid against Stage 2's format
- [ ] `GET /tags` returns 1550 entries
- [ ] `GET /tags/MS-OIL.OVERALL.PROP_MS_0` returns the dictionary entry
- [ ] `GET /tags/MS-OIL.OVERALL.PROP_MS_0/value` returns a numeric value
- [ ] `GET /tags/MS-OIL.OVERALL.PROP_MS_0/history?since=2026-05-10T00:00:00Z` returns time series
- [ ] `GET /docs` loads Swagger UI
- [ ] OpenAPI spec exported to `docs/api/openapi.yaml` and committed
- [ ] Memory growth < 200 MB after 1000 sequential requests

---

## Stage 4 — OPC-UA Server (asyncua)

### Behavior

**File:** `2.automation/stage4/opcua_server.py` (~300-400 lines) + `node_hierarchy.py` (~150 lines)

**1. Bootstrap**
- Load tag dictionary
- Build OPC-UA node hierarchy (see Node Hierarchy below)
- Initialize `asyncua.Server` on `opc.tcp://localhost:4840/refinery_twin/`
- No security policy (demo mode); document hardening for production
- Set application URI: `urn:RefineryDigitalTwin:server`
- Set product URI: `urn:RefineryDigitalTwin:dwsim_petroleum_distillation`

**2. Node hierarchy**

```
Server/
└── Objects/                              (standard)
    └── Refinery/                         (custom namespace)
        ├── PetroleumSide/
        │   ├── MaterialStreams/
        │   │   ├── MS-OIL/
        │   │   │   ├── OVERALL/
        │   │   │   │   ├── PROP_MS_0  (Variable, Double, "Temperature")
        │   │   │   │   ├── PROP_MS_1  (Variable, Double, "Pressure")
        │   │   │   │   └── ...
        │   │   │   ├── VAPOR/
        │   │   │   └── LIQUID/
        │   │   ├── MS-CRUDE/
        │   │   └── ... (656 petroleum-side variables grouped this way)
        │   ├── EnergyStreams/
        │   │   ├── ES-CONDENSER_DUTY  (Variable, Double, "Energy Flow")
        │   │   └── ES-REBOILER_DUTY
        │   └── Columns/
        │       └── DC-101/
        │           ├── STAGE_1/
        │           ├── STAGE_2/
        │           └── ...
        └── ThermalOilLoop/                (894 thermal-oil-side variables)
            ├── MaterialStreams/
            ├── EnergyStreams/
            └── Equipment/
                ├── PUMP-001/
                ├── HEATER-001/
                └── ...
```

Node naming uses tag dictionary's normalized IDs (e.g., `MS-OIL`, `OVERALL`, `PROP_MS_0`). Subsystem split (petroleum vs thermal oil) follows Phase 0a's override rules.

**3. Update loop**

```python
async def update_loop():
    while not shutdown:
        # Find current Stage 2 active hour file
        active_file = find_current_jsonl(stage2_dir)
        # Read just the last line (latest snapshot)
        latest_snapshot = read_last_line(active_file)
        if latest_snapshot and latest_snapshot["solved"]:
            for tag_id, value in latest_snapshot["tags"].items():
                node = node_map.get(tag_id)
                if node:
                    await node.write_value(value)  # OPC-UA write triggers subscription notifications
        await asyncio.sleep(5)  # poll every 5 s; new snapshot arrives every 30 s in steady state
```

**4. Subscriptions**
- OPC-UA clients can subscribe to any node
- When `node.write_value()` is called and the value changed, asyncua automatically pushes the change to subscribers
- Default subscription publishing interval: 1000 ms (1 s)

**5. Server status node**
- Standard `Server/ServerStatus/State` node reports server health
- Custom `Refinery/StreamerHealth/` node tree:
  - `LastSnapshotCycle` (Variable, Int32)
  - `LastSnapshotTimestamp` (Variable, DateTime)
  - `Stage2Running` (Variable, Boolean) — true if active hour file is being written

**6. Error handling**
- Stage 2 not running → all variables hold last-good value with `Bad_NoCommunication` quality
- New snapshot has `solved: false` → variables hold last-good value with `Uncertain_LastUsableValue` quality
- Server crash on write error → log, continue; don't kill the server

**7. Run command**

```bash
cd 2.automation/stage4
arch -x86_64 ../.venv-x86/bin/python opcua_server.py
```

### Acceptance criteria — Stage 4

- [ ] `opcua_server.py` exists at `2.automation/stage4/opcua_server.py`
- [ ] Server starts on `opc.tcp://localhost:4840/refinery_twin/` without errors
- [ ] Browse via `asyncua` Python client (or UaExpert) shows the hierarchy under `Objects/Refinery/`
- [ ] All 1550 tags appear as Variable nodes in the correct subsystem folder (petroleum 656, thermal_oil 894)
- [ ] Reading a node's value returns the latest snapshot's value for that tag
- [ ] Subscribing to a node and waiting 30 s shows at least one value-change notification (next solve cycle)
- [ ] Server `ServerStatus/State` reports `Running`
- [ ] Custom `StreamerHealth/Stage2Running` reports `true` while Stage 2 is active
- [ ] OPC-UA clients can connect anonymously (no security mode for demo)
- [ ] Memory growth < 300 MB after 30 minutes of running with active subscriptions
- [ ] Sample browse paths documented in `docs/api/opcua_browse_paths.md`

---

## Combined acceptance — A2 end-to-end

- [ ] Both Stage 3 and Stage 4 run simultaneously (different ports, no conflict)
- [ ] Both running alongside Stage 2 streamer + Stage 5 producer (4 processes total on Mac)
- [ ] CPU usage of Stage 3 idle: <2%
- [ ] CPU usage of Stage 4 idle (no subscribers): <2%
- [ ] CPU usage of Stage 4 with 10 subscribed nodes: <5%
- [ ] All 4 processes survive a 1-hour smoke run (architectural — no need for actual full hour)
- [ ] Both `README.md` files written with run commands, port info, sample queries/browse paths
- [ ] OpenAPI spec checked into `docs/api/openapi.yaml`
- [ ] OPC-UA browse paths documented in `docs/api/opcua_browse_paths.md`

## Outputs

| | |
|---|---|
| `2.automation/stage3/api.py` | FastAPI server |
| `2.automation/stage3/README.md` | run commands, endpoints, examples |
| `2.automation/stage4/opcua_server.py` | OPC-UA server main |
| `2.automation/stage4/node_hierarchy.py` | tag-dict → OPC-UA tree builder |
| `2.automation/stage4/README.md` | run commands, browse hints, client examples |
| `docs/api/openapi.yaml` | exported OpenAPI 3.0 spec |
| `docs/api/opcua_browse_paths.md` | sample browse paths for industrial clients |

## Anti-goals

- ✗ No setpoint write-back via REST or OPC-UA (read-only for A2; write-back is post-demo)
- ✗ No authentication / authorization (local-only; no internet exposure in A2)
- ✗ No TLS / OPC-UA security mode (insecure for demo; document hardening)
- ✗ No persistence in REST or OPC-UA (both read JSONL on demand; no separate DB)
- ✗ No Event Hubs / cloud integration (Stage 5 already does that)
- ✗ No Twin ontology (F2)
- ✗ No agents (F3)
- ✗ No web UI (F5)
- ✗ No multi-substrate scenarios
- ✗ No modification of prior stages

## Methodology rules

- Read-only: Stage 3 and Stage 4 never write back to DWSIM or modify any state files
- Don't crash on transient JSONL read failures (file rotating, mid-write line) — log warning, retry
- Don't import from prior stages — re-implement tail-reading patterns where needed
- Lane discipline: no edits to `1.AgenticAI/` or other lanes
- Conventional commits on `phase-4-protocols`
- All endpoints / nodes are deterministic given Stage 2 input — same JSONL → same response

## Out of scope

- Setpoint write-back (post-demo, would need DWSIM session reuse — different architecture)
- F2 / F3 / F5
- Cloud-side REST / OPC-UA gateways (different design — exposing from Eventhouse rather than local)
- Authentication, RBAC, audit logging (production hardening, post-demo)
- Performance load testing beyond steady-state idle

## Definition of done

1. All Stage 3 acceptance criteria met
2. All Stage 4 acceptance criteria met
3. Combined acceptance met
4. Both `README.md` files committed
5. OpenAPI spec + OPC-UA browse paths committed
6. `phase-4-protocols` branch pushed
7. Operator approval; architect issues F2 (twin ontology) briefing

## Cost commitments

- **A2 adds zero cloud cost.** Both servers run locally on Mac.
- No new licenses, no new Azure resources.
- A1's recurring (~$25/mo Power BI Pro + Event Hubs) continues unchanged.

## Hand-off note for Claude Code

Stage 3 and Stage 4 are independent — could be implemented in parallel by two Claude Code sessions, or sequentially in one. Recommend **sequential**: do Stage 3 first (FastAPI is more familiar territory), get it accepted, then Stage 4.

For Stage 3:
- FastAPI is ergonomic. Use Pydantic models for response schemas where it improves clarity, but don't over-model — Stage 2 snapshot is already structured.
- Don't add a database, cache layer, or async background workers for A2. KISS: each request reads JSONL fresh.
- For `/snapshots/range`, decompressing closed `.gz` files on-demand is fine for demo cadence (rare requests, small data). If a client hammers it, that's their problem; we won't optimize prematurely.
- OpenAPI spec auto-generated by FastAPI; export it to `docs/api/openapi.yaml` as part of acceptance.

For Stage 4:
- `asyncua` is the Python OPC-UA library to use. Mature, actively maintained.
- The node hierarchy is the design heart — get it right. Use the tag dictionary's `subsystem` field (petroleum vs thermal_oil) for the top-level split. Within each subsystem, group by ObjType prefix (MS-, ES-, DC-, etc.).
- `node.write_value()` is the API for pushing updates; subscription mechanics are handled by asyncua.
- Don't try to serve all 1550 tags on a single update tick — they all live in the same snapshot, but writing all 1550 in a single `await` storm could spike CPU. Batch via `asyncio.gather` if needed, or write sequentially in the loop (asyncua handles backpressure).
- Test with `asyncua` Python client first (write a 30-line script that connects, browses, reads, subscribes). Then UaExpert for visual verification.

For both:
- Tail the same JSONL files Stage 5 reads. Don't import Stage 5's code; re-implement the tail logic. The pattern is simple: find current hour's `.jsonl`, read latest line(s), parse, use.
- Don't keep file handles open across requests/cycles unless necessary — files rotate hourly, and stale handles will block rotation.

Branch: `phase-4-protocols`. Conventional commits. Don't push without operator approval.

End of briefing.
