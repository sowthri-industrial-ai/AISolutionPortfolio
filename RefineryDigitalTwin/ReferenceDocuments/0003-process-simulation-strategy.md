# ADR-0003 — DWSIM as primary process simulator with Python thermo fallback

**Status:** Accepted
**Date:** 2026-05-02
**Deciders:** Architect

## Context

The CDU twin needs a process simulator that is convincing enough to interview against. It must produce:

- Plausible mass and energy balance for a CDU
- Time-series state for ~80–100 tags
- Six injectable scenario modes (feed change, heater fouling, pump failure, column upset, compressor surge, ESD)
- Stable behaviour over hours of run-time

For refinery applications, the natural choice is **DWSIM**, an open-source process simulator broadly comparable to commercial tools (Aspen HYSYS, ProMax). Alternatively, we can write a simplified Python thermodynamics model from scratch.

## Decision

We will use **DWSIM** as the primary simulator behind the Simulation Service, with a **lightweight Python thermodynamics module** as a documented fallback. The platform interacts with the simulator only through the Simulation Service's REST API; the underlying engine is swappable.

## Alternatives considered

### Option A — DWSIM only

- **Pros:** Real chemical-engineering tool. Accurate-enough thermodynamics. Recognisable name in interviews. Open source.
- **Cons:** .NET-based; Python integration is via Mono or COM. Setup is non-trivial cross-platform. CI complexity.
- **Why not chosen alone:** Single point of failure for the whole simulator path.

### Option B — Custom Python thermo only

- **Pros:** Pure Python, no native dependencies. Easy CI. Full control.
- **Cons:** Less defensible in interview ("you wrote a thermodynamics model from scratch?"). Harder to scale to additional units later.
- **Why not chosen alone:** Loses the credibility of a real simulator.

### Option C — DWSIM primary + Python fallback (chosen)

- **Pros:** Best of both. DWSIM gives real-tool credibility; fallback keeps the demo runnable on any laptop.
- **Cons:** Two implementations of the simulation interface to maintain.
- **Why chosen:** Resilience and demo-portability outweigh the duplication cost.

### Option D — Aspen HYSYS / commercial

- **Pros:** Industry standard.
- **Cons:** Licence cost prohibitive for a portfolio project. Closed source.
- **Why not chosen:** Not viable.

## Consequences

### Positive

- Demo runs on a fresh laptop in 10 minutes regardless of DWSIM availability.
- Fallback mode is also CI-friendly (no Mono in pipeline).
- The Simulation Service API design is forced to be engine-agnostic, which is good architecture.

### Negative

- Two code paths to maintain. Discipline required to keep both passing the same tests.
- Risk of "fallback rot" — if no one runs DWSIM regularly, it bit-rots. Mitigated by a weekly CI job.

### Neutral

- The simulator is not a hot-path during normal telemetry generation; it is invoked for scenarios. Engine swap latency is acceptable.

## Implementation approach

```
SimulationService
   ├── interfaces/
   │   └── simulator.py          # abstract base
   ├── engines/
   │   ├── dwsim_engine.py       # DWSIM-backed
   │   └── thermo_engine.py      # Python fallback
   └── scenarios/
       ├── feed_quality_change.py
       ├── heater_fouling.py
       ├── pump_failure.py
       ├── column_upset.py
       ├── compressor_surge.py
       └── emergency_shutdown.py
```

Engine selected via environment variable `SIM_ENGINE=dwsim|thermo` (default: `dwsim`, falls back automatically if DWSIM init fails).

## Compliance / cross-cutting

- **Reusability:** The interface-engine pattern means swapping in a different simulator for petrochem (e.g., custom kinetics) does not change the platform.
- **Testing:** Both engines must pass the same suite of "scenario produces expected qualitative state change" tests.

## Validation

- Six scenarios produce visible, qualitatively-correct state changes
- Engine swap is a single env-var flip with no platform changes
- DWSIM and thermo paths agree within 10% on key indicators (column top temp, heater outlet temp)

## Open follow-ups

- DWSIM deployment artefact for production (Docker image with Mono runtime) — milestone M2
