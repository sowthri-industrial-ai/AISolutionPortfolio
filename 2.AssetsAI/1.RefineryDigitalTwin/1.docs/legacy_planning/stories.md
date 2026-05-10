# Backlog — Stories

> Format: `[ ]` open · `[~]` in progress · `[x]` done · `[!]` blocked
> Sizes: **S** = ≤2h, **M** = 2–4h, **L** = ½ day. Anything bigger needs splitting.

---

## E1 — Foundations

### `[ ] E1-S01` Initialise repo skeleton
**Size:** S
**Acceptance:**
- Directory tree matches `docs/01-architecture.md` §"Repository layout"
- `.gitignore`, `.editorconfig`, `LICENSE` (MIT), `CODEOWNERS` present
- Top-level `Makefile` with stub targets: `setup`, `test`, `lint`, `run`, `demo`, `status`, `infra-up`, `infra-down`
- README badges render (status, architecture, docs)
**Depends on:** —

### `[ ] E1-S02` Python project setup
**Size:** S
**Acceptance:**
- `pyproject.toml` with deps from `docs/03-tech-stack.md` exact-pinned
- `uv` or `pip-tools` lock generated
- `ruff`, `mypy --strict`, `pytest` configured
- `make setup` provisions a working venv; `make lint` passes on empty repo
**Depends on:** E1-S01

### `[ ] E1-S03` Node project setup
**Size:** S
**Acceptance:**
- `dashboard/frontend/package.json` with React + Vite + Tailwind + shadcn/ui
- `eslint`, `prettier`, `vitest` configured
- `npm run dev` starts; `npm run lint` passes; `npm run test` runs (zero tests OK)
**Depends on:** E1-S01

### `[ ] E1-S04` Docker Compose dev stack
**Size:** M
**Acceptance:**
- `docker-compose.dev.yml` with: Postgres 16, TimescaleDB extension, Redpanda (Kafka mode), MinIO
- All services healthy via `make dev-up`
- `.env.example` documents required vars; `.env` in `.gitignore`
**Depends on:** E1-S01

### `[ ] E1-S05` GitHub Actions CI
**Size:** M
**Acceptance:**
- Workflow runs on PR and push to main
- Jobs: `lint-python`, `lint-frontend`, `test-python`, `test-frontend`, `build-images`
- Status badges in README reflect CI
- Concurrency group prevents overlapping runs on same branch
**Depends on:** E1-S02, E1-S03

### `[ ] E1-S06` Bicep skeleton for Azure resources
**Size:** M
**Acceptance:**
- `infra/azure/main.bicep` provisions: resource group, Event Hub namespace, Event Hub, Key Vault, Postgres flexible server (small SKU)
- `make infra-up` deploys; `make infra-down` tears down
- All resources tagged `project=refinetwin`, `env=demo`
**Depends on:** E1-S04
**Note:** Stub the Fabric workspace; real Fabric provisioning is E1-S07

### `[ ] E1-S07` Terraform skeleton for Fabric workspace
**Size:** M
**Acceptance:**
- `infra/fabric/main.tf` uses `microsoft/fabric` provider
- Provisions workspace + Eventhouse + Lakehouse
- Outputs: workspace ID, Eventhouse query URI
- Documented fallback: if Fabric provider blocked, equivalent ADX cluster via Bicep
**Depends on:** E1-S06
**Note:** ADR-0001 fallback path

### `[ ] E1-S08` `make status` command
**Size:** S
**Acceptance:**
- Prints: current milestone, in-progress stories, blocked stories, last 5 commits, lint/test pass/fail
- Pulls in-progress stories from `docs/backlog/stories.md` by parsing `[~]` markers
- Used by Claude Code at session start
**Depends on:** E1-S01

---

## E2 — Domain & Ontology

### `[ ] E2-S01` Equipment class definitions
**Size:** M
**Acceptance:**
- `docs/ontology/equipment-classes.json` defines: centrifugal pump, fired heater, distillation column, shell-and-tube exchanger, control valve
- Each class has: ISO 14224 classification, key tags (with role + meaning + units), failure modes
- JSON Schema (`docs/ontology/schema.json`) validates
**Depends on:** E1-S02
**Refs:** `docs/02-isa95-ontology.md` §4

### `[ ] E2-S02` CDU equipment instances
**Size:** M
**Acceptance:**
- 12+ equipment instances across all classes, named per `docs/02` (H-101, P-100..104, E-101/102/110, C-101, plus 4 control valves)
- All resolved against equipment classes
- All have `parent_id` chain up to enterprise
- All have at least one `relationship` (FeedsInto / RecoversHeatFrom / etc.)
**Depends on:** E2-S01

### `[ ] E2-S03` Tag dictionary
**Size:** L
**Acceptance:**
- `docs/ontology/tag-dictionary.json` lists all ~80–100 tags
- Each tag has: canonical_id, asset_id, role, meaning, units, AB tag, Siemens DB ref, OPC-UA NodeId
- Validated against tag-schema.json
- Total tag count documented in README
**Depends on:** E2-S02

### `[ ] E2-S04` Ontology JSON schema validation in CI
**Size:** S
**Acceptance:**
- CI step validates all `docs/ontology/*.json` against their schemas
- PR fails if validation fails
- Helpful error message on failure
**Depends on:** E2-S03

### `[ ] E2-S05` Ontology loader library
**Size:** M
**Acceptance:**
- Python package `refinetwin.ontology` with: `load_ontology(path) -> Ontology`, `Ontology.get_asset(id)`, `.descendants(id)`, `.ancestors(id)`, `.find_by_class(class)`, `.relationships(id)`
- Pydantic models for all entity types
- 100% mypy strict, 90%+ test coverage
- Loads full CDU in <200ms
**Depends on:** E2-S03

### `[ ] E2-S06` Sample SOPs and P&ID descriptions
**Size:** M
**Acceptance:**
- `data/sops/` contains 4–6 SOPs as Markdown: heater_startup, pump_changeover, column_upset_response, esd_procedure, charge_pump_swap, hot_oil_circulation
- `data/p-and-id/` contains text descriptions of CDU P&ID at three zoom levels (unit, module, equipment)
- All written in standard refinery English; references actual asset IDs from ontology
**Depends on:** E2-S02
**Note:** Used by Safety and Ops agents (E7)

---

## E3 — Process Simulator

### `[ ] E3-S01` Simulator skeleton + main loop
**Size:** S
**Acceptance:**
- `simulator/main.py` runs a 1Hz tick loop
- Holds state for all equipment instances loaded from ontology
- Logs structured tick summary every 60s
**Depends on:** E2-S05

### `[ ] E3-S02` Steady-state CDU model (Python thermo)
**Size:** L
**Acceptance:**
- Mass balance closes within 0.5% across the unit
- Energy balance closes within 1% across the unit
- Top temp, bottom temp, side draws stable at expected ranges (top 130°C, kero 200°C, diesel 280°C, residue 360°C)
- Documented in `simulator/README.md` with the equations used
**Depends on:** E3-S01
**Refs:** ADR-0003

### `[ ] E3-S03` Realistic noise + drift on tags
**Size:** S
**Acceptance:**
- Each tag has configurable Gaussian noise (sigma per tag class)
- Slow drift baked in for fouling-prone tags (heater outlet, exchanger DP)
- No pathological values (e.g., negative pressure)
**Depends on:** E3-S02

### `[ ] E3-S04` Pump model
**Size:** M
**Acceptance:**
- Each pump: head-vs-flow curve, NPSH calc, suction/discharge pressures, vibration, bearing temp
- Realistic startup transient (0 to running in 5s)
- Run/stop status switches change all dependent tags consistently
**Depends on:** E3-S02

### `[ ] E3-S05` Fired heater model
**Size:** M
**Acceptance:**
- Four pass outlet temps controllable
- Fuel gas flow ↔ outlet temp feedback
- Stack O2 / temp / draft consistent
- Skin temp tag with realistic profile
**Depends on:** E3-S02

### `[ ] E3-S06` DWSIM integration (best-effort)
**Size:** L
**Acceptance:**
- `engines/dwsim_engine.py` calls DWSIM via Python bridge for CDU simulation
- Same scenario produces qualitatively similar output to thermo engine within 10% on key tags
- Falls back gracefully to thermo engine if DWSIM init fails
- Documented setup in `simulator/README.md`
**Depends on:** E3-S02
**Refs:** ADR-0003
**Note:** If DWSIM proves unstable, mark this as deferred and stay on thermo engine; record in ADR follow-up.

### `[ ] E3-S07` Scenario: feed quality change
**Size:** M
**Acceptance:**
- Light → heavy crude switch propagates: column profile changes, heater duty changes, product yields change
- Reverts on command
- Visible in tags within 5 minutes of trigger
**Depends on:** E3-S05

### `[ ] E3-S08` Scenario: heater fouling
**Size:** S
**Acceptance:**
- Pass outlet temps drift down over hours; fuel gas flow rises to compensate
- Linear progression configurable
- Triggers high-skin-temp alarm at expected threshold
**Depends on:** E3-S05

### `[ ] E3-S09` Scenario: pump failure
**Size:** S
**Acceptance:**
- Configurable pump (default P-100): vibration spike, bearing temp rise, eventual trip
- Downstream pressures and flows respond consistently
- Standby pump auto-start option
**Depends on:** E3-S04

### `[ ] E3-S10` Scenario: column upset
**Size:** M
**Acceptance:**
- DP rise (flooding) or DP collapse (weeping) selectable
- Tray temp profile distorts realistically
- Reflux pump amps respond
**Depends on:** E3-S02

### `[ ] E3-S11` Scenarios: compressor surge + ESD
**Size:** M
**Acceptance:**
- Compressor surge: discharge oscillation, rapid trip
- ESD: shutdown sequence following SOP order, valves to fail-safe positions, all pumps stopped, heater fuel cut
**Depends on:** E3-S09

---

## E4 — OT Integration

### `[ ] E4-S01` PLC tag namespace generator
**Size:** M
**Acceptance:**
- For every tag in dictionary, generates AB and Siemens-style names per ADR-0006
- Produces `simulator/plc_tags.json` mapping canonical → namespace-specific
- Idempotent: regeneration produces no diff if dictionary unchanged
**Depends on:** E2-S03

### `[ ] E4-S02` OPC-UA server skeleton
**Size:** M
**Acceptance:**
- `asyncua` server listens on configurable port
- Address space namespace 2 = `refinetwin`
- Server discoverable; can be browsed by `opcua-client` GUI
**Depends on:** E1-S04

### `[ ] E4-S03` OPC-UA address space population
**Size:** L
**Acceptance:**
- Address space mirrors ISA-95 hierarchy: Sites → Units → Equipment → Variables
- Every tag is a `Variable` with proper `EngineeringUnits` and `EURange`
- Variables link to simulator state (push updates on tick)
- Generated from tag dictionary, not handcrafted
**Depends on:** E4-S02, E3-S02

### `[ ] E4-S04` OPC-UA subscriptions + history
**Size:** M
**Acceptance:**
- Subscriptions deliver updates within 100ms of value change
- HistoryRead returns last 24h for any variable
- Multiple concurrent subscribers supported
**Depends on:** E4-S03

### `[ ] E4-S05` Bridge: OPC-UA → Event Hub
**Size:** L
**Acceptance:**
- `ingestion/bridge/main.py` subscribes to all dictionary tags
- Serialises events per ADR-0006 §"The bridge serialises events as"
- Publishes to Event Hub in batches
- Backoff and retry on Event Hub failures
- Health endpoint reports subscription state
**Depends on:** E4-S04, E1-S06

### `[ ] E4-S06` Bridge: ontology ID enrichment
**Size:** S
**Acceptance:**
- Bridge resolves tag → asset_id, unit_id, site_id, enterprise_id at startup
- All emitted events carry these IDs
- Cache invalidation on bridge restart
**Depends on:** E4-S05, E2-S05

### `[ ] E4-S07` OT/IT segregation enforcement
**Size:** S
**Acceptance:**
- CI check: no module under `simulator/` or `ingestion/opcua-server/` may import from `twin-platform/`, `ai-agents/`, `dashboard/`
- Bridge is the only allowed crossing
- Failure produces clear CI error
**Depends on:** E4-S05
**Refs:** ADR-0005

---

## E5 — Real-Time Data Plane

### `[ ] E5-S01` Eventhouse schema
**Size:** M
**Acceptance:**
- KQL DDL in `ingestion/fabric/eventhouse_schema.kql` creates: `Telemetry`, `Alerts`, `AgentTranscripts`, `PlatformLogs`
- All tables include schema_version + ingestion_timestamp
- Update policy from raw to typed tables
**Depends on:** E1-S07

### `[ ] E5-S02` Event Stream definition (Fabric)
**Size:** M
**Acceptance:**
- Event Stream connects Event Hub → Eventhouse Telemetry table
- Drops events with missing required fields (logged to deadletter)
- Documented in `ingestion/README.md`
**Depends on:** E5-S01

### `[ ] E5-S03` OneLake landing for cold data
**Size:** M
**Acceptance:**
- Event Stream additionally writes to OneLake Lakehouse
- Partitioned by date and site
- Compaction job documented (manual for demo, automated for prod)
**Depends on:** E5-S02

### `[ ] E5-S04` Local-dev substitute: Postgres + TimescaleDB ingestion
**Size:** M
**Acceptance:**
- `ingestion/dev_consumer.py` reads from Redpanda, writes to TimescaleDB hypertable
- Schema parity with Eventhouse
- Runs under Docker Compose
**Depends on:** E1-S04

### `[ ] E5-S05` Materialised views: 1-min, 5-min, 1-hour aggregates
**Size:** M
**Acceptance:**
- KQL update policies build rollups
- Same logic in TimescaleDB continuous aggregates
- Used by historian service and Power BI
**Depends on:** E5-S01, E5-S04

### `[ ] E5-S06` End-to-end smoke test
**Size:** S
**Acceptance:**
- Test: simulator → OPC-UA → bridge → Event Hub → Eventhouse → KQL query returns the value within 3s
- Same test against local-dev stack
- Runs in CI nightly (cloud) and on every PR (local)
**Depends on:** E5-S04, E4-S05

### `[ ] E5-S07` Eventhouse ingestion latency monitoring
**Size:** S
**Acceptance:**
- Dashboard/metric of bridge_emit_time → eventhouse_ingest_time
- Alert if p95 > 5s
**Depends on:** E5-S06

### `[ ] E5-S08` Backpressure handling test
**Size:** M
**Acceptance:**
- Bridge under sustained 10x normal rate does not crash
- Eventhouse ingestion does not lose events
- Documented behaviour in `ingestion/README.md`
**Depends on:** E5-S06

### `[ ] E5-S09` Cold-path query helpers
**Size:** S
**Acceptance:**
- Python utility wraps OneLake/Lakehouse queries via Spark or DuckDB
- Same interface as Eventhouse helpers
- Used by anomaly service for training data pulls
**Depends on:** E5-S03

---

## E6 — Twin Platform Services

### `[ ] E6-S01` Service skeleton template
**Size:** S
**Acceptance:**
- `twin-platform/_template/` is a copy-paste FastAPI service: structlog, OTel, health endpoint, config via env, Dockerfile
- README in template explains how to fork it for a new service
**Depends on:** E1-S02

### `[ ] E6-S02` Ontology Service (read API)
**Size:** L
**Acceptance:**
- Endpoints: `GET /assets/{id}`, `/assets/{id}/descendants`, `/assets/{id}/ancestors`, `/assets/by-class/{class}`, `/relationships/{id}`
- Loads ontology JSON on boot, serves from in-memory cache
- p95 < 50ms
- Postgres optional persistence for runtime overrides
**Depends on:** E6-S01, E2-S05

### `[ ] E6-S03` Historian Service
**Size:** L
**Acceptance:**
- Endpoints: `GET /tags/{id}/history?from=&to=&interval=&agg=`, `/tags/{id}/latest`, `/tags?prefix=`
- Queries Eventhouse in prod; TimescaleDB in dev (decided by env var)
- p95 < 200ms for 24h windows
**Depends on:** E5-S05

### `[ ] E6-S04` Anomaly Service: model registry
**Size:** M
**Acceptance:**
- Models stored in `twin-platform/anomaly_service/models/` with metadata (asset_class, version, training data ref)
- Service can load by ID and version
- Trained models tracked in Postgres registry
**Depends on:** E6-S01

### `[ ] E6-S05` Anomaly Service: pump bearing model
**Size:** M
**Acceptance:**
- Trained on synthetic data from simulator (vibration + bearing temp time series)
- Detects elevated risk during pump failure scenario (E3-S09) within 5 min
- Returns RUL estimate with confidence band
**Depends on:** E6-S04, E3-S09

### `[ ] E6-S06` Anomaly Service: heater fouling model
**Size:** M
**Acceptance:**
- Trained on synthetic data
- Detects fouling progression (E3-S08) before alarm threshold
- Returns days-to-cleaning estimate
**Depends on:** E6-S04, E3-S08

### `[ ] E6-S07` Anomaly Service: column upset detector
**Size:** M
**Acceptance:**
- Multivariate detector across DP, tray temps, reflux flow
- Detects flooding/weeping within 2 minutes of trigger
**Depends on:** E6-S04, E3-S10

### `[ ] E6-S08` Simulation Service API
**Size:** M
**Acceptance:**
- `POST /scenarios/run` triggers a scenario; returns run_id
- `GET /scenarios/{run_id}` returns status + state delta
- Idempotent on repeated calls with same params
**Depends on:** E3-S07..E3-S11

### `[ ] E6-S09` Drift detection
**Size:** M
**Acceptance:**
- River-based online drift detector on each anomaly model
- Posts drift events to Eventhouse Alerts
- Documented threshold per model
**Depends on:** E6-S05, E6-S06, E6-S07

### `[ ] E6-S10` Alert publication
**Size:** S
**Acceptance:**
- Anomaly service writes alerts to Eventhouse with: asset_id, severity, kind, evidence, timestamp
- Alerts retrievable via Historian/Alerts endpoint
**Depends on:** E6-S03, E6-S05

### `[ ] E6-S11` Service-to-service auth
**Size:** S
**Acceptance:**
- All services use shared JWT or managed-identity in prod
- Local dev uses static service tokens from `.env`
- Documented in each service README
**Depends on:** E6-S02, E6-S03, E6-S04

### `[ ] E6-S12` Platform integration test
**Size:** M
**Acceptance:**
- End-to-end test: simulate pump failure → anomaly service detects → alert in Eventhouse → historian returns → ontology resolves asset → all in <1 minute
**Depends on:** E6-S05, E6-S10

---

## E7 — Agentic AI

### `[ ] E7-S01` MCP server skeleton
**Size:** M
**Acceptance:**
- `ai-agents/mcp_server/` runs an MCP server with one demo tool (`echo`)
- Connectable from Claude Desktop and from custom Python client
- stdio and HTTP transports both work
**Depends on:** E1-S02
**Refs:** ADR-0004

### `[ ] E7-S02` MCP tool: get_asset_state
**Size:** M
**Acceptance:**
- Calls Ontology + Historian services
- Returns: asset entity + last 5 minutes of key tag values + active alerts
- Audit log entry per call
**Depends on:** E7-S01, E6-S02, E6-S03, E6-S10

### `[ ] E7-S03` MCP tool: query_historian
**Size:** S
**Acceptance:**
- Tool signature: tag, from, to, agg
- Pass-through to historian service with result formatting
- Rejects queries spanning >7 days (cost guard)
**Depends on:** E7-S01, E6-S03

### `[ ] E7-S04` MCP tool: list_active_alerts
**Size:** S
**Acceptance:**
- Filters by unit_id and severity
- Returns enriched alert objects (alert + asset info)
**Depends on:** E7-S01, E6-S10

### `[ ] E7-S05` MCP tool: predict_failure
**Size:** S
**Acceptance:**
- Calls anomaly service for given asset
- Returns RUL, confidence, contributing factors
**Depends on:** E7-S01, E6-S05

### `[ ] E7-S06` MCP tool: run_what_if
**Size:** M
**Acceptance:**
- Triggers Simulation Service scenario
- Polls until completion
- Returns state delta summary
**Depends on:** E7-S01, E6-S08

### `[ ] E7-S07` MCP tool: get_sop + RAG
**Size:** L
**Acceptance:**
- Indexes SOPs + P&ID descriptions into pgvector
- Tool retrieves top-k chunks for given equipment_class + situation
- Returns chunks with source references
**Depends on:** E7-S01, E2-S06

### `[ ] E7-S08` Reliability agent
**Size:** M
**Acceptance:**
- Profile in `ai-agents/agents/reliability.py` with system prompt + allow-list
- Demo question: "Should I be worried about P-100?" produces a grounded answer using predict_failure + query_historian
- Conversation logged to OneLake
**Depends on:** E7-S02, E7-S03, E7-S05

### `[ ] E7-S09` Operations agent
**Size:** M
**Acceptance:**
- Demo question: "Why did the kerosene draw temperature drop in the last hour?" produces a useful answer combining alerts + historian + SOP
**Depends on:** E7-S02, E7-S03, E7-S04, E7-S07

### `[ ] E7-S10` Energy + Safety agents
**Size:** M
**Acceptance:**
- Energy: "What's the energy cost of switching to heavy crude?" runs run_what_if and explains
- Safety: "What are the failure modes for H-101?" answers from get_failure_modes + get_sop, no execution
**Depends on:** E7-S06, E7-S07

---

## E8 — Dashboards & UX

### `[ ] E8-S01` React app skeleton
**Size:** S
**Acceptance:**
- Vite app with router, layout (top bar + sidebar), shadcn/ui set up
- Three routes: `/`, `/assets/:id`, `/agents/:agent`
- Reads from `VITE_API_BASE` env var
**Depends on:** E1-S03

### `[ ] E8-S02` Twin platform API client
**Size:** S
**Acceptance:**
- Generated TypeScript types from FastAPI OpenAPI specs
- React Query hooks: `useAsset`, `useAssetHistory`, `useAlerts`
**Depends on:** E8-S01, E6-S02, E6-S03

### `[ ] E8-S03` Real-time WebSocket bridge
**Size:** M
**Acceptance:**
- WebSocket endpoint on twin platform pushes new alerts and tag updates
- Reconnect with exponential backoff
- Hook: `useLiveTags(tag_ids[])`
**Depends on:** E8-S02

### `[ ] E8-S04` Map view
**Size:** L
**Acceptance:**
- MapLibre canvas with custom CDU layout (auto-laid-out from ontology relationships)
- Equipment markers click → asset detail
- Live state colours assets (green/amber/red)
**Depends on:** E8-S03

### `[ ] E8-S05` Asset detail page
**Size:** M
**Acceptance:**
- Header with asset id, class, ontology breadcrumb
- Live tag values for key tags
- 24h chart of selected tag
- Active alerts list
- "Open in Power BI" link
**Depends on:** E8-S02

### `[ ] E8-S06` Alerts panel
**Size:** S
**Acceptance:**
- Side panel always visible
- Sorted by severity then time
- Click alert → highlights asset on map
**Depends on:** E8-S03

### `[ ] E8-S07` Agent chat
**Size:** L
**Acceptance:**
- Per-agent chat pages
- Streams Claude responses
- Renders tool-call traces (which tools fired, with inputs/outputs)
- Conversation persisted to OneLake transcript table
**Depends on:** E8-S02, E7-S08, E7-S09
**Note:** Tool-trace rendering is a deliberate showcase feature

### `[ ] E8-S08` Power BI Embedded dashboard
**Size:** L
**Acceptance:**
- One `.pbix` file with: OEE proxy, energy intensity, yield by product, alarm rate
- DirectQuery against Eventhouse
- Embed token flow working in dashboard `/bi` route
**Depends on:** E5-S05

### `[ ] E8-S09` Demo script
**Size:** S
**Acceptance:**
- `docs/demo-script.md` walks a 10-minute interview demo: open dashboard, trigger pump failure, watch alert appear, ask reliability agent, run energy scenario
- Tested end-to-end; timestamps verified
**Depends on:** E8-S04, E8-S07, E7-S10
