# RefineTwin — Industrial Digital Twin Platform for Refinery Operations

> A reference implementation of an end-to-end Industrial AI / Digital Twin platform for a Crude Distillation Unit (CDU), built on Microsoft Fabric Real-Time Intelligence with agentic AI workflows over the Model Context Protocol. Designed as a **reusable, multi-industry foundation** extensible to petrochemicals, pharma, and discrete manufacturing.

[![status](https://img.shields.io/badge/status-in%20development-yellow)]() [![architecture](https://img.shields.io/badge/architecture-frozen-green)]() [![docs](https://img.shields.io/badge/docs-comprehensive-blue)]()

---

## Why this project exists

Most "Industrial AI" portfolio projects stop at a Jupyter notebook with a predictive-maintenance model. This one goes further: it is a working reference architecture covering the full stack a real refinery digital twin requires — OT protocol ingestion, ISA-95 ontology, real-time stream processing, process simulation, anomaly detection, agentic AI, and operator-facing dashboards. Built to demonstrate **architectural fluency**, not just code.

## What's in scope

A Crude Distillation Unit (CDU) digital twin with four nested twin levels (Enterprise, Network, Plant, Asset), six what-if simulation scenarios, four agentic AI workflows (reliability, operations, energy, safety), real-time KQL analytics on Fabric Eventhouse, and a dual-mode dashboard (Power BI + React/MapLibre).

## Architecture at a glance

```
┌─────────────────┐     ┌─────────────────┐     ┌──────────────────┐     ┌────────────────┐
│   CDU Process   │────▶│   OPC-UA Server │────▶│  Azure Event Hub │────▶│  Fabric RTI    │
│   Simulator     │     │  (PLC tag-style)│     │                  │     │  Event Stream  │
│   + DWSIM       │     │                 │     │                  │     │                │
└─────────────────┘     └─────────────────┘     └──────────────────┘     └───────┬────────┘
                                                                                 │
                        ┌────────────────────────────────────────────────────────┴──┐
                        │                                                           │
                        ▼                                                           ▼
                ┌───────────────┐                                          ┌────────────────┐
                │  Eventhouse   │                                          │   OneLake      │
                │  (KQL, hot)   │                                          │  (Lakehouse)   │
                └───────┬───────┘                                          └────────┬───────┘
                        │                                                           │
                        ├──────────────────┬─────────────────┬───────────────────┐  │
                        ▼                  ▼                 ▼                   ▼  ▼
                ┌──────────────┐  ┌────────────────┐  ┌─────────────┐  ┌────────────────┐
                │ Twin Service │  │ Anomaly Service│  │ MCP Server  │  │   Power BI     │
                │ (ISA-95)     │  │  (PdM models)  │  │  (4 agents) │  │   Embedded     │
                └──────┬───────┘  └────────┬───────┘  └──────┬──────┘  └────────────────┘
                       │                   │                 │
                       └───────────┬───────┴─────────┬───────┘
                                   ▼                 ▼
                          ┌─────────────────────────────────┐
                          │   Web App (React + MapLibre)    │
                          │   Real-time map · Alerts · KPIs │
                          └─────────────────────────────────┘
```

A richer Mermaid version lives in [`docs/01-architecture.md`](docs/01-architecture.md).

## Tech stack (frozen)

| Layer | Choice | Why |
|---|---|---|
| Process simulation | DWSIM (open-source) + custom Python thermo | Real chemical engineering tool, scriptable |
| OT protocol | OPC-UA (`asyncua`) | Standard refinery industrial protocol |
| Stream ingestion | Azure Event Hub | Fabric-native, AMQP/Kafka compatible |
| Real-time analytics | Microsoft Fabric RTI (Event Stream + Eventhouse + KQL) | Production-grade real-time analytics on Azure |
| Lakehouse | OneLake (Fabric) | Unified governed storage |
| Twin / ontology service | FastAPI + Pydantic + Postgres | ISA-95 hierarchy, well-typed, fast |
| Anomaly detection | scikit-learn + River (online learning) | Time-series PdM, drift-aware |
| AI agents | Anthropic Claude + custom MCP server | JD-aligned; MCP is a differentiator |
| Dashboard (KPI) | Power BI Embedded | Closest to real Fabric stack |
| Dashboard (real-time) | React + MapLibre + WebSocket | Live alerts, map view |
| IaC | Bicep (Azure) + Terraform (Fabric workspaces) | Production patterns |
| CI/CD | GitHub Actions | Standard |

Decisions are recorded as ADRs in [`docs/adr/`](docs/adr/).

## Repository layout

```
refinery-digital-twin/
├── README.md                          # This file
├── docs/
│   ├── 00-vision-and-scope.md
│   ├── 01-architecture.md
│   ├── 02-isa95-ontology.md
│   ├── 03-tech-stack.md
│   ├── 04-non-functional-requirements.md
│   ├── 05-glossary.md
│   ├── CLAUDE.md                      # Instructions for Claude Code dev
│   ├── adr/                           # Architecture Decision Records
│   ├── ontology/                      # ISA-95 hierarchy as JSON
│   ├── diagrams/                      # Mermaid + draw.io sources
│   └── backlog/
│       ├── epics.md
│       ├── stories.md
│       └── milestones.md
├── simulator/                         # Synthetic CDU + OPC-UA server
├── ingestion/                         # Event Hub + Fabric Event Stream
├── twin-platform/                     # FastAPI services
├── ai-agents/                         # MCP server + 4 agents
├── dashboard/                         # React + Power BI
├── infra/                             # Bicep + Terraform
├── data/                              # Sample CDU configurations and assay data
└── tests/
```

## How this maps to the JD

| JD requirement | Where this project demonstrates it |
|---|---|
| Process manufacturing experience | CDU is the canonical process unit |
| Solution architecture & docs | 6+ ADRs, NFRs, ontology models, this README |
| ISA-95 / ISA-88 | Four-tier ontology in `docs/02-isa95-ontology.md` |
| Allen-Bradley & Siemens PLCs | Tag namespaces simulated in `simulator/plc_tag_simulator.py` |
| OPC-UA, OPC-DA, MT Connect | Real OPC-UA server in simulator |
| Industrial historians | PI-style time-series API in `twin-platform/historian_service` |
| AI/ML for OEE, quality, PdM, anomaly detection | All four in `twin-platform/anomaly_service` |
| Visualisation & operator enablement | Power BI + React real-time dashboard |
| Pilot → multi-site rollout | Documented in milestones, infra-as-code |
| IEC 62443 cybersecurity | ADR-0005 + reference network segmentation |
| OT / IT / business stakeholder bridging | Architecture document explicitly maps personas |

## Quickstart

```bash
# Prerequisites: Docker, Python 3.11+, Node 20+, Azure CLI
git clone <this-repo>
cd refinery-digital-twin
docker compose -f docker-compose.dev.yml up -d   # local dev: simulator + Postgres + Eventhouse-substitute
make seed                                         # load sample CDU configuration
make run-simulator                                # start CDU simulator + OPC-UA server
make run-platform                                 # start twin + anomaly + MCP services
make run-dashboard                                # open dashboard at http://localhost:3000
```

Full setup including Fabric provisioning is in [`docs/CLAUDE.md`](docs/CLAUDE.md).

## Status

Architecture is **frozen** as of the date of this commit. Active build is tracked in [`docs/backlog/milestones.md`](docs/backlog/milestones.md). See the backlog for what's being implemented, what's done, and what's deferred.

## Author

Built as a portfolio reference architecture by [Your Name] — Industrial AI Solution Architect.
RefineryTwin is an independent project built using public standards and open-source tooling.
