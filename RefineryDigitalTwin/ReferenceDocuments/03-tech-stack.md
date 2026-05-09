# 03 — Technology Stack (Frozen)

**Status:** Frozen — changes require an ADR
**Last review:** [date]

This document is the single source of truth for technology choices. If a tool or version differs between code and this document, the document is wrong — open a PR. Anything not on this list is not allowed without an ADR.

## 1. Languages and runtimes

| Language | Version | Used for | Why |
|---|---|---|---|
| Python | 3.11 | Simulator, platform services, agents | Mature scientific stack, type hints |
| TypeScript | 5.4+ | React frontend | Type safety in the UI |
| Node.js | 20 LTS | Frontend build, MCP transport | Long-term support |
| KQL | n/a | Eventhouse queries | Native to Fabric |
| Bash / Make | n/a | Orchestration | Universal |

**Not allowed:** Python <3.11, JavaScript without TypeScript, Java/Go/Rust (no project need).

## 2. Process simulation

| Component | Choice | Fallback |
|---|---|---|
| Process simulator | DWSIM 8.x (open source) | Python thermodynamics module (Antoine, simple energy balance) |
| Pressure drop / flow | Custom Python with `numpy` | n/a |
| Reaction kinetics | Out of scope (CDU is mostly physical separation) | n/a |

DWSIM is preferred because it is real chemical-engineering software with a Python COM/Mono bridge. If integration proves fragile, ADR-0003 documents the lightweight thermo fallback.

## 3. OT / industrial protocols

| Component | Choice | Notes |
|---|---|---|
| OPC-UA server | `asyncua` | Pure Python, async, full address space |
| OPC-UA client (bridge) | `asyncua` | Same library |
| MQTT (optional) | `paho-mqtt` | Only if we add edge gateway path |
| Modbus | Not in scope | Documented as extension point |
| MT Connect | Not in scope | Documented as extension point |

## 4. Stream and storage

| Layer | Production | Local dev |
|---|---|---|
| Event ingest | Azure Event Hub | Redpanda (Kafka-compatible) |
| Stream routing | Fabric Event Stream | Custom Python consumer |
| Hot store | Fabric Eventhouse (KQL) | Postgres + TimescaleDB |
| Lakehouse | OneLake (Delta) | MinIO + Delta Lake |
| Twin metadata | Postgres 16 | Postgres 16 (same) |

The two-mode setup means CI and laptop dev never need cloud.

## 5. Twin platform services

Every service follows the same skeleton.

| Service | Framework | Persistence |
|---|---|---|
| Ontology Service | FastAPI + Pydantic v2 | Postgres |
| Simulation Service | FastAPI + Pydantic v2 | Stateless (calls DWSIM) |
| Anomaly Service | FastAPI + Pydantic v2 | Postgres (model registry) |
| Historian Service | FastAPI + Pydantic v2 | Eventhouse (prod) / TimescaleDB (dev) |

ML libraries:
- `scikit-learn` — baseline models
- `river` — online learning, drift detection
- `pyod` — anomaly detection benchmarks
- `joblib` — model serialisation

## 6. AI / Gen AI

| Component | Choice | Version |
|---|---|---|
| LLM | Anthropic Claude | claude-sonnet-4 (default) |
| MCP SDK | `@modelcontextprotocol/python-sdk` | latest stable |
| MCP transport | stdio for local, HTTP for distributed | both supported |
| Embeddings (RAG) | `text-embedding-3-small` (OpenAI) or local `bge-small` | configurable |
| Vector DB | `pgvector` (Postgres extension) | use existing Postgres |
| Prompt observability | Langfuse (self-hosted, optional) | optional |

**Why not LangChain/LangGraph:** for four agents with clear tool boundaries, MCP is more aligned with the JD and avoids framework lock-in. ADR-0004 explains.

## 7. Frontend

| Component | Choice |
|---|---|
| Framework | React 18 + Vite |
| Routing | React Router 6 |
| State | Zustand (small), React Query (server state) |
| Map | MapLibre GL JS |
| Charts | Recharts |
| UI primitives | shadcn/ui + Tailwind |
| WebSocket | native + reconnection wrapper |

## 8. Power BI

| Component | Choice |
|---|---|
| Authoring | Power BI Desktop |
| Data source | DirectQuery against Eventhouse (KQL) |
| Embedding | Power BI Embedded with App-Owns-Data |
| Fallback | Apache Superset against TimescaleDB (ADR-0007 if triggered) |

## 9. Infrastructure

| Layer | Tool |
|---|---|
| Azure resources | Bicep |
| Fabric workspace | Terraform with `fabric` provider |
| Local orchestration | Docker Compose |
| Production orchestration | AKS (documented, not deployed) |
| Secrets | Azure Key Vault (prod), `.env.local` (dev) |
| Identity | Azure managed identity (prod), service principals (dev) |

## 10. CI / CD

| Stage | Tool |
|---|---|
| Source | GitHub |
| CI | GitHub Actions |
| Tests | pytest, vitest |
| Lint | ruff, mypy, eslint, prettier |
| Container | Docker, multi-stage builds |
| Container registry | GitHub Container Registry (ghcr.io) |
| Release | semver tags, automated changelog |

## 11. Observability

| Concern | Tool |
|---|---|
| Logs | structlog (Python), pino (Node) → JSON to stdout |
| Traces | OpenTelemetry SDK → OTLP exporter |
| Metrics | OpenTelemetry → Prometheus or Azure Monitor |
| Dashboard | Grafana (dev), Azure Monitor (prod) |

## 12. Security

| Concern | Approach |
|---|---|
| Secrets | Key Vault prod, `.env` dev (in `.gitignore`) |
| Identity | Managed identity prod, SP dev |
| Network (prod) | Private endpoints for Event Hub + Fabric |
| Network (dev) | Docker network isolation |
| Code scanning | GitHub Dependabot + CodeQL |
| Container scanning | Trivy in CI |
| MCP authorisation | Per-agent tool allow-list |

Detailed in ADR-0005.

## 13. Testing strategy

| Level | Tooling | Coverage target |
|---|---|---|
| Unit | pytest, vitest | 80% on platform services |
| Integration | pytest with testcontainers | All cross-service paths |
| End-to-end | Playwright | Critical user journeys |
| Simulator validation | golden-output regression | Six what-if scenarios |

## 14. Things we are explicitly NOT using

So Claude Code does not introduce them:

- **Kubernetes for local dev** — Docker Compose is the only local stack
- **Microservices framework hype** (Dapr, Istio) — direct HTTP between services
- **GraphQL** — REST + Pydantic models
- **MongoDB** — Postgres only
- **Redis** — not needed for this scale
- **gRPC** — REST is fine for the agent count we have
- **Kotlin / JVM** — no project need
- **NVIDIA Omniverse** — out of scope, see vision doc
- **Custom auth** — Azure AD prod, none in dev
- **Front-end UI library that isn't shadcn/ui** — already chosen
- **Any new dependency that isn't on this list** without an ADR

## 15. Version pinning policy

- Python deps: exact pins via `requirements.txt` (or `pyproject.toml` with `==`)
- Node deps: lockfile committed (`package-lock.json`)
- Docker base images: SHA-pinned in CI, tag-pinned in dev
- Major version bumps require an ADR
