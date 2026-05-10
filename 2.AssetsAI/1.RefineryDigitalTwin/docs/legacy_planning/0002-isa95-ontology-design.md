# ADR-0002 — ISA-95 hierarchical ontology as the platform spine

**Status:** Accepted
**Date:** 2026-05-02
**Deciders:** Architect

## Context

The platform must serve four distinct twin levels (Enterprise, Network, Plant, Asset). Telemetry, alerts, simulations, agent queries, and dashboards all need a consistent way to identify and traverse equipment. We need a single domain model that everything else binds to.

Three patterns exist in industry:

1. **Flat tag space** — every measurement is a flat string; equipment is implicit. PI System default.
2. **ISA-95 hierarchy** — formal nested model: Enterprise → Site → Area → Process Cell → Unit → Equipment → Sub-equipment.
3. **Custom domain graph** — bespoke per project, often based on P&ID parsing.

## Decision

We will use **ISA-95 hierarchical ontology** with **ISO 14224 equipment classification** for failure-mode taxonomy, declared in versioned JSON files under `docs/ontology/`, served by a dedicated **Ontology Service** that is the single source of truth for asset identity across the platform.

## Alternatives considered

### Option A — Flat tag space

- **Pros:** Simplest to implement. Every PLC speaks this language natively.
- **Cons:** No notion of "the pump that feeds this column." Network twin becomes impossible. Agents cannot reason about impact.
- **Why not chosen:** Defeats the digital-twin proposition. We are building a twin, not a tag store.

### Option B — ISA-95 + ISO 14224 (chosen)

- **Pros:** International standard. JD lists ISA-95. Naturally supports the four twin levels. ISO 14224 gives standard failure modes for reliability work. Maps cleanly to refinery, petchem, pharma, and discrete manufacturing.
- **Cons:** More upfront modelling effort. Engineers unfamiliar with the standard need a primer.
- **Why chosen:** It is what a real industrial AI architect would do, and it is what the JD asks for.

### Option C — Custom domain graph

- **Pros:** Maximum flexibility.
- **Cons:** Reinvents standards. Not portable. Hard to defend in interview ("why not just use ISA-95?").
- **Why not chosen:** No upside given B exists.

## Consequences

### Positive

- Every component speaks one language. Ontology IDs flow through telemetry, KQL, alerts, MCP tools, and dashboards.
- Network twin emerges naturally from `relationships` arrays.
- Reusability across industries is by construction (change equipment classes, hierarchy stays).
- Reliability features get ISO 14224 failure modes "for free."

### Negative

- Ontology JSON files become a critical artefact. Bad edits break the platform.
- Adding a new equipment class requires touching simulator, ontology JSON, OPC-UA tag dictionary, KQL schemas, and dashboard mappings.
- Ontology evolution needs a migration story.

### Neutral

- The Ontology Service becomes a hot-path read dependency. Cache aggressively; ADR-0008 if scaling becomes an issue.

## Compliance / cross-cutting

- **Reusability:** The whole point. ISA-95 is industry-neutral.
- **Governance:** Ontology files reviewed by architect on every PR. Schema-validated in CI.
- **AI agents:** MCP tools resolve to ontology IDs. The agent never sees raw tag strings.

## Validation

- The CDU model loads from JSON in under 200ms.
- All telemetry events carry resolvable `asset_id`, `unit_id`, `area_id`, `site_id`, `enterprise_id`.
- Unit tests cover hierarchy traversal: `get_descendants(unit_id)`, `get_ancestors(asset_id)`, `find_by_class(class)`.
- Schema validation prevents commits with malformed ontology JSON.

## Open follow-ups

- Ontology versioning and migration strategy (ADR if/when needed)
- Whether to publish ontology as a separate package for reuse across future industries
