# ADR-0006 — OPC-UA as the canonical OT integration protocol

**Status:** Accepted
**Date:** 2026-05-02
**Deciders:** Architect

## Context

A "process manufacturing AI" platform that does not speak industrial protocols is not credible. The JD lists OPC-UA, OPC-DA, and MT Connect as required competencies. A real refinery exposes thousands of tags via OPC-UA from DCS / historian gateways.

We need to:

- Expose simulated PLC state through a real industrial protocol
- Demonstrate OT-to-IT data crossing patterns
- Keep the path single and auditable

## Decision

We will implement a **real OPC-UA server** in the simulator (using `asyncua`) that exposes the full PLC tag set through a standards-compliant address space, and a **single dedicated bridge** that subscribes to the OPC-UA server and publishes to Azure Event Hub. OPC-DA and MT Connect are **not implemented** but documented as drop-in extension points.

## Alternatives considered

### Option A — Mock telemetry directly into Event Hub (skip OPC-UA)

- **Pros:** Simplest. Fewer moving parts.
- **Cons:** Bypasses the OT layer entirely. Loses the JD bullseye. Cannot be defended in interview.
- **Why not chosen:** Defeats the purpose.

### Option B — Real OPC-UA server + dedicated bridge (chosen)

- **Pros:** Real protocol exercises real patterns: address space design, subscriptions, security, namespace mapping. Bridge component demonstrates OT/IT segregation. Reusable for future PLC additions.
- **Cons:** More setup. `asyncua` learning curve.
- **Why chosen:** Authentic and demonstrable.

### Option C — OPC-UA + OPC-DA + MT Connect all implemented

- **Pros:** Maximum protocol coverage.
- **Cons:** OPC-DA is COM-based and Windows-only; MT Connect is an HTTP standard with little overlap with the refinery domain (it's discrete-manufacturing-oriented). Effort doesn't match value.
- **Why not chosen:** OPC-UA covers the credibility need.

## Consequences

### Positive

- Path from "tag value changes in the simulator" to "appears in Eventhouse" is real, not faked.
- Demonstrates OPC-UA address-space design with namespaces and standard NodeIDs.
- Bridge becomes the architectural enforcement point for OT/IT segregation.
- Future PLC integration (real or simulated) plugs into the same OPC-UA path.

### Negative

- Local dev environment needs three containers: simulator, OPC-UA server, bridge. Slightly heavier startup.
- `asyncua` is solid but its quirks (e.g., subscription timing, security profiles) need careful handling.

### Neutral

- The OPC-UA address space is generated from the tag dictionary, not handcrafted. Single source of truth.

## Address space design

```
Server: opc.tcp://0.0.0.0:4840/refinetwin/server
Namespace 0: standard OPC-UA
Namespace 1: server diagnostics
Namespace 2: refinetwin                      ← our content
  Objects/
    Sites/
      GulfCoast/
        Units/
          CDU1/
            Equipment/
              H-101/                          ← BrowseName for fired heater
                Variables/
                  PassOutletTemp1            ← Float, R/W, EU=°C
                  ...
              P-100/
                Variables/
                  DischargePressure
                  ...
```

Variables expose:
- `Value` (live)
- `EngineeringUnits`
- `EURange`
- Subscribable (10ms granularity)
- Historical reads via `HistoryRead` extension service (last 24h in memory)

## Bridge design

Single Python process. Configuration:
```yaml
opcua:
  endpoint: opc.tcp://opcua-server:4840/refinetwin/server
  security_policy: Basic256Sha256
  subscriptions:
    - node_id: ns=2;s=GulfCoast.CDU1.H-101.PassOutletTemp1
      sampling_interval_ms: 1000
    - ...
eventhub:
  connection_string: ${EVENTHUB_CONNECTION_STRING}
  entity_path: telemetry
batch:
  max_size: 100
  max_wait_ms: 200
```

The bridge serialises events as:
```json
{
  "schema_version": "1.0",
  "tag_id": "GulfCoast.CDU1.H-101.PassOutletTemp1",
  "asset_id": "H-101",
  "unit_id": "CDU1",
  "site_id": "GulfCoast",
  "value": 365.2,
  "units": "°C",
  "quality": "Good",
  "timestamp": "2026-05-02T12:34:56.789Z"
}
```

Ontology IDs (`asset_id`, `unit_id`, `site_id`) are resolved from the tag dictionary at bridge startup, so downstream consumers do not need to do this mapping.

## Compliance / cross-cutting

- **Security:** OPC-UA Basic256Sha256 in production deployment; None in local dev (documented). Certificates managed by `asyncua` auto-generation in dev.
- **Reusability:** Real PLCs can replace the OPC-UA server with no platform changes.
- **OT segregation:** Bridge is the only conduit (see ADR-0005).

## Validation

- OPC-UA Compliance Test Tool (or `opcua-client` equivalent) can browse the server and read all variables
- Bridge maintains stable subscriptions over 24h with no message loss in normal conditions
- Tag-to-Eventhouse latency p95 < 2 seconds end-to-end

## Open follow-ups

- OPC-UA security in production deployment (cert management) — milestone M2
- Historical read via `HistoryRead` from real OPC-UA HA servers (extension)
