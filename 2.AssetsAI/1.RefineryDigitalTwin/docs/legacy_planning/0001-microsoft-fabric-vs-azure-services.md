# ADR-0001 — Build on Microsoft Fabric Real-Time Intelligence, not stitched Azure services

**Status:** Accepted
**Date:** 2026-05-02
**Deciders:** Architect

## Context

We need a real-time data platform that ingests OPC-UA telemetry, performs sub-second analytics, lands governed data in a lakehouse, and feeds dashboards plus AI agents. The two viable patterns are:

1. **Stitched Azure services** — Event Hub + Stream Analytics + ADX + ADLS + Synapse + Purview + Power BI, integrated by hand.
2. **Microsoft Fabric Real-Time Intelligence** — Event Stream + Eventhouse + OneLake + Power BI, as one SaaS platform.

This decision shapes the entire IT-zone architecture and dictates skill requirements, cost, and delivery time.

## Decision

We will build on **Microsoft Fabric Real-Time Intelligence (RTI)** with **Eventhouse + OneLake** as the primary data plane, with a documented Azure-only fallback path for the case where the Fabric trial expires or licensing becomes a blocker.

## Alternatives considered

### Option A — Stitched Azure services (Event Hub + ADX + ADLS + Synapse + Power BI)

- **What it is:** Each Azure service used directly, integrated via Bicep/Terraform.
- **Pros:** No Fabric licence required. Mature, well-documented services. Maximum flexibility.
- **Cons:** Ten-plus services to provision, monitor, and bill. Schema versioning across services. Handcrafted lineage. No unified governance. Significantly more glue code.
- **Why not chosen:** This is the default that the architectural community is moving away from for unified industrial-data platforms. Reproducing that pivot toward unified governance is a feature of this project, not a regression.

### Option B — Microsoft Fabric RTI + OneLake

- **What it is:** Single SaaS platform, native real-time + lakehouse + BI.
- **Pros:** Unified governance via OneLake. One billing meter. Native Power BI integration via DirectQuery on Eventhouse. Built-in lineage. JD-aligned vocabulary across Microsoft's industrial AI stack.
- **Cons:** Trial-bound capacity. Fabric is younger; some features evolve quickly. Vendor lock-in to Microsoft.
- **Why chosen:** The JD lists Microsoft Fabric and digital twin platforms explicitly; the unified-platform value proposition is the architectural claim being demonstrated; production-ready real-time + lakehouse + BI in a single workspace is the strongest pattern available for this use case.

### Option C — Open-source equivalent (Kafka + Flink + Iceberg + Trino + Superset)

- **What it is:** Confluent / Kafka + Apache Flink + Apache Iceberg + Trino + Apache Superset.
- **Pros:** No vendor lock-in. Genuinely portable.
- **Cons:** Many moving parts to operate. Does not match the JD vocabulary. Higher operational burden than the budget allows.
- **Why not chosen:** Off-strategy for this portfolio piece. Reserved as a future "open-stack RefineTwin" extension, not current scope.

## Consequences

### Positive

- Architecture vocabulary maps 1:1 to the JD and to Microsoft's industrial AI stack (Event Stream, Eventhouse, KQL, OneLake, Fabric IQ).
- DirectQuery from Power BI to Eventhouse is one click, not a service-bus-shaped dance.
- OneLake is the single governed home for telemetry, ontology, and AI transcripts.
- Demo path is short: one workspace, one capacity, four artefacts.

### Negative

- Tied to Fabric availability and licensing. If the trial expires mid-build, we move to fallback.
- Fabric APIs evolve; some stories may need rework after platform updates.
- Some advanced features (custom Stream Analytics jobs, ADX cluster-level controls) are hidden behind Fabric abstractions.

### Neutral

- We ship Bicep for Azure resources and Terraform for Fabric workspaces. Two IaC tools, both small surfaces.

## Compliance / cross-cutting

- **Security:** Fabric integrates with Entra ID; managed identity available for service-to-service. Documented in ADR-0005.
- **Reusability:** The Fabric pattern is identical regardless of industry; ontology and simulator change. Reusability claim holds.
- **Cost:** Fabric trial covers the demo period. Production cost scenarios documented in `docs/04-non-functional-requirements.md`.

## Fallback (documented operational plan)

If Fabric trial expires or capacity becomes unavailable:

1. Replace Event Stream with **Azure Stream Analytics**.
2. Replace Eventhouse with **Azure Data Explorer (ADX) cluster**. KQL is the same.
3. Replace OneLake with **Azure Data Lake Gen2** + Delta tables.
4. Power BI continues unchanged (now DirectQuery to ADX).
5. Update Bicep; remove Terraform Fabric module.

The platform services and dashboards do not change. This is the architectural insurance policy.

## Validation

- The Fabric workspace can be provisioned by `make infra-up` in under 10 minutes.
- Telemetry from simulator reaches Eventhouse in under 2 seconds (Story PERF-001).
- KQL queries used by dashboard return in under 500ms p95 (Story PERF-002).
- The fallback plan can be exercised on demand (Story RES-001).

## Open follow-ups

- ADR-0007: Power BI Embedded vs Apache Superset (pending licensing confirmation)
