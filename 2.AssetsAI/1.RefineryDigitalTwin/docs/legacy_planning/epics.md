# Backlog — Epics

> The product is decomposed into **8 epics** delivered across **4 milestones**. Each epic owns a coherent slice of capability and ships independently. Stories within an epic are sized to be implemented by Claude Code in a single session (1–4 hours).

## Epic catalogue

| ID | Epic | Owns | Stories |
|---|---|---|---|
| **E1** | Foundations | repo, CI, IaC scaffolding, dev container | 8 |
| **E2** | Domain & Ontology | ISA-95 model, tag dictionary, equipment classes | 6 |
| **E3** | Process Simulator | CDU model, PLC tag generation, six scenarios | 11 |
| **E4** | OT Integration | OPC-UA server, bridge, OT/IT crossing | 7 |
| **E5** | Real-Time Data Plane | Event Hub, Fabric RTI, Eventhouse, OneLake | 9 |
| **E6** | Twin Platform Services | ontology, simulation, anomaly, historian APIs | 12 |
| **E7** | Agentic AI | MCP server, four agents, tool allow-lists | 10 |
| **E8** | Dashboards & UX | React app, Power BI, real-time updates | 9 |

**Total: 72 stories.** Velocity assumption: 4–6 stories/day with Claude Code under architect review = ~3–4 weeks calendar time for an evenings-and-weekends pace.

## Epic dependencies

```
E1 ──┬──▶ E2 ──┬──▶ E3 ──▶ E4 ──┬──▶ E5 ──▶ E6 ──┬──▶ E7
     │         │                 │              │
     └─────────┴─────────────────┴──────────────┴──▶ E8 (frontend can mock back-ends early)
```

E1 and E2 are blocking for everything. E3–E5 form the data backbone. E6 unblocks E7 and E8. E8 can stub data and develop in parallel with E5–E7.

## Milestone alignment

| Milestone | Epics in scope | Outcome |
|---|---|---|
| **M1 — Skeleton walks** | E1, E2, E3 (partial) | Simulator produces tags; ontology serves entities; CI green |
| **M2 — Data flows** | E3 (rest), E4, E5 | OPC-UA → Event Hub → Eventhouse end-to-end with one scenario |
| **M3 — Twin breathes** | E6, E7 (partial) | Twin platform serves all four services; reliability and ops agents working |
| **M4 — Demo-ready** | E7 (rest), E8, polish | Energy + safety agents; dashboard live; six scenarios runnable; README + demo script complete |

## Out-of-scope items kept on the radar

These are not stories. They live here so we don't forget them and so reviewers see we considered them.

- 3D / Omniverse visualisation (vision doc out-of-scope)
- Real PLC hardware integration
- Multi-tenant / multi-site (single CDU only)
- Mobile / responsive UX beyond desktop
- OPC-DA, MT Connect, Modbus protocols
- Historian write-back / control loop closure
- Real-time control (we observe; we do not actuate)
- Aspen HYSYS / commercial simulator
- Production-grade hardening (documented as gap in ADR-0005)

## Story file structure

Stories are in `docs/backlog/stories.md`, grouped by epic. Each story has:

- ID (e.g., `E3-S04`)
- Title
- Status: `[ ]` open / `[~]` in progress / `[x]` done / `[!]` blocked
- Acceptance criteria (testable)
- Dependencies (other story IDs)
- Estimate (S/M/L based on Claude Code session length)
- Notes (optional; includes ADR refs, gotchas, files affected)
