# 00 — Vision & Scope

**Status:** Frozen
**Owner:** Architect
**Last review:** [date]

## 1. Vision

Build a working, demonstrable Industrial Digital Twin platform for a Crude Distillation Unit that proves architectural fluency across the full Industrial AI stack — OT integration, real-time analytics, process simulation, agentic AI, and operator enablement — built on Microsoft Fabric Real-Time Intelligence in the refinery / process-manufacturing domain.

The deliverable is a **GitHub repository that an interview panel can clone, read, and run within 30 minutes**, supported by architecture documentation that demonstrates how each technology choice maps to a real-world manufacturing AI programme.

## 2. Why a refinery

- The target role is Industrial AI Solution Architect for **process manufacturing**. A refinery is the canonical process unit.
- Refineries directly exercise every JD requirement: PLCs (AB + Siemens), OPC-UA, ISA-95, IEC 62443, historians, OEE, predictive maintenance, anomaly detection.
- The architecture is intentionally domain-agnostic — only the domain layer changes between industries. This proves the "reusable, multi-industry foundation" claim concretely.

## 3. In scope

**Process model**
A simplified Crude Distillation Unit with 12–15 named assets across the major equipment classes:
- 1 atmospheric distillation column
- 1 fired heater (atmospheric)
- 3 product pumps (kerosene, diesel, residue)
- 1 crude charge pump
- 2 heat exchangers (preheat train)
- 1 reflux pump
- 4 control valves on key streams
- Associated transmitters (T, P, F, L) — approximately 80–100 simulated tags

**Twin levels (ISA-95-aligned)**
1. Enterprise — refinery KPIs, throughput, energy, yield
2. Site / Network — inter-unit flows, product distribution
3. Plant / Unit — CDU process state, mass / energy balance
4. Asset / Sub-asset — individual equipment health and performance

**Six what-if scenarios**
1. Crude feed quality change (light / heavy crude switch)
2. Fired heater tube fouling progression
3. Charge pump degradation / failure
4. Distillation column upset (flooding / weeping)
5. Compressor surge on overhead system
6. Emergency shutdown (ESD) sequence

**Four agentic AI workflows**
1. Reliability — predictive failure on rotating equipment
2. Operations — shift-handover, console support, deviation explanation
3. Energy — optimisation suggestions across the preheat train
4. Safety — LOPA / process-safety query agent over P&IDs and SOPs

**Dashboards**
- Power BI Embedded — KPIs, OEE, energy, yield, alarm rates
- React + MapLibre — real-time map of unit, alerts, asset state, agent chat

## 4. Out of scope (explicit)

- 3D / NVIDIA Omniverse visualisation. Replaced with 2D map + asset cards. Documented in ADR.
- Real refinery data. Everything is synthetic; the simulator is the source of truth.
- Multi-tenant SaaS. Single-tenant reference deployment only.
- Production-grade security hardening. We document IEC 62443 patterns; we do not implement zero-trust networking end-to-end.
- Mobile apps.
- Multi-language UI.
- Real PLC hardware connection. The OPC-UA server is software-only.

## 5. Success criteria

The project is "done" for interview purposes when:

1. A reviewer can clone the repo, run `make demo`, and see live data flowing from simulator → Event Hub → Eventhouse → dashboard within 10 minutes on their laptop.
2. All six what-if scenarios run from the dashboard and produce visible state changes.
3. At least two AI agents (reliability + operations) respond to natural-language questions over real twin data via MCP.
4. Architecture documentation answers the top 10 questions an interviewer might ask, with cross-references between docs and code.
5. The build-vs-buy decision (Fabric in-house vs COTS) is defended in an ADR with clear architectural reasoning.

## 6. Non-goals masquerading as goals

These are tempting but explicitly rejected:

- **"Make it production-ready."** It's a demonstrator. Production-readiness is a documented gap, not a feature.
- **"Add more scenarios."** Six is the budget. Adding a seventh delays MVP.
- **"Support more agents."** Four is the budget. Quality over quantity.
- **"Cover the full refinery."** CDU only. Other units are noted as extension points.

## 7. Personas

| Persona | Need | Where served |
|---|---|---|
| Interview panel | Quick comprehension, depth on demand | README, ADRs, working demo |
| Plant operator | Real-time visibility, fast root-cause | React dashboard, ops agent |
| Reliability engineer | PdM insights, RUL trends | Reliability agent, Power BI |
| Plant manager | OEE, energy, yield KPIs | Power BI |
| OT / Controls engineer | OPC-UA tag access, network segmentation | Simulator, IEC 62443 ADR |
| Enterprise architect | Reference patterns, ADRs, ISA-95 | Documentation set |

## 8. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Fabric trial expires mid-build | Medium | High | Azure-only fallback documented in ADR-0001 |
| DWSIM integration too heavy | Medium | Medium | Lightweight Python thermo as fallback |
| MCP server complexity | Low | Medium | Reference Anthropic MCP examples, use SDK |
| Power BI embedding licensing | Medium | Low | Substitute with Apache Superset documented in ADR |
| Time overrun | High | Medium | Strict scope; defer not extend; milestone gates |

## 9. Approval

This vision is frozen. Changes require an ADR.

Architect: ____________________   Date: ____________
