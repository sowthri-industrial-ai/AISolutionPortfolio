# ADR-0005 — IEC 62443-aligned security posture for the demonstrator

**Status:** Accepted
**Date:** 2026-05-02
**Deciders:** Architect

## Context

Refineries are critical infrastructure. The JD lists IEC 62443 (industrial automation cybersecurity) as a key competency. A digital-twin project that ignores this is unconvincing.

We need to:

- Demonstrate security thinking aligned to IEC 62443 zones-and-conduits
- Implement what's reasonable for a portfolio demo
- Document the gap to production rigorously

## Decision

We adopt a **demonstrator-grade IEC 62443 alignment** that implements the structural patterns (zones, conduits, segmentation, identity, least-privilege) faithfully but does not aim for full certification-level controls. Production gaps are explicitly documented.

## Zone model

```
┌─ Level 0: Process (simulator internals) ──────────────────┐
│  ┌─ Level 1: Basic Control (PLC tag simulator) ─────────┐ │
│  │  ┌─ Level 2: Supervisory (OPC-UA Server) ──────────┐ │ │
│  │  │                                                  │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
                          ▲
                          │  Conduit: OPC-UA → Bridge (only path out)
                          ▼
┌─ Level 3.5: DMZ (Bridge) ─────────────────────────────────┐
│  - One process, one purpose                               │
│  - Outbound only to Event Hub                             │
│  - No inbound from IT zone                                │
└────────────────────────────────────────────────────────────┘
                          ▲
                          │  Conduit: AMQP/HTTPS to Event Hub
                          ▼
┌─ Level 3 / 4: IT Zone ────────────────────────────────────┐
│  Fabric workspace, platform services, dashboards, agents  │
└────────────────────────────────────────────────────────────┘
```

## Implemented controls

### Identity and access

- Azure managed identity for all platform-to-Fabric calls in production deployment
- Service principal with namespace-scoped Event Hub send permission for the bridge
- No Fabric admin permissions on agent or platform identities
- MCP per-agent tool allow-list enforced server-side

### Network

- Local dev: Docker networks isolating OT and IT
- Production deployment (documented): private endpoints for Event Hub, Fabric capacity, Postgres
- No public ingress except Application Gateway → web app

### Data

- Telemetry encrypted in transit (TLS to Event Hub)
- Telemetry encrypted at rest (Eventhouse and OneLake defaults)
- Secrets in Azure Key Vault (production); `.env` files git-ignored (dev)
- No PII or operator credentials in telemetry

### Audit

- All MCP tool invocations logged with agent identity
- Bridge logs every OPC-UA → Event Hub crossing
- Eventhouse stores 30 days of platform self-monitoring logs

### Segregation of duties

- Simulator and OT zone code never imports IT-zone modules
- Bridge is the only crossing component
- Code review verifies no direct OT-to-IT imports (CI check)

## Not implemented (production gaps, documented)

| Control | Status | Closing requires |
|---|---|---|
| Hardware data diodes for OT-to-IT | Not implemented | Real OT environment |
| Asset inventory automation | Not implemented | CMDB integration |
| Threat detection (SIEM rules) | Not implemented | Microsoft Sentinel integration |
| Vulnerability scanning of OT components | Not implemented | Real PLC firmware |
| Continuous compliance monitoring | Not implemented | Microsoft Defender for IoT |
| Supply chain (SBOM) verification | Partial | Trivy scans containers; no SBOM gate |
| Disaster recovery / backup tested | Not implemented | Multi-region setup |
| Pen-tested hardening | Not implemented | External engagement |

These gaps are honest, documented, and form natural follow-on work — exactly what a real architect plans for.

## Alternatives considered

### Option A — Ignore IEC 62443 entirely

- **Why not:** Loses the JD bullseye and the architect-thinking signal.

### Option B — Full IEC 62443 SL-2 implementation

- **Why not:** Out of scope for a demonstrator. Months of work; needs real OT.

### Option C — Demonstrator-grade alignment with documented gaps (chosen)

- **Why:** Honest, achievable, demonstrates the reasoning that matters.

## Consequences

### Positive

- Defensible answer to "how would you secure this in production?"
- Clear separation of OT and IT in code structure (CI-enforced)
- Audit trails support agent governance discussions

### Negative

- Some tasks (e.g., adding a new MCP tool) require touching agent allow-lists in addition to server registration
- Local dev requires Docker network setup; not just `python main.py`

### Neutral

- The gap document grows over time; it should be reviewed quarterly

## Validation

- CI fails if any OT-zone module imports an IT-zone module
- All Azure resources in production deployment use managed identity
- A penetration-test-style review of the design produces no critical findings against the implemented scope

## Open follow-ups

- Microsoft Defender for IoT integration plan (post-MVP)
- Sentinel detection rules for unusual MCP tool patterns
