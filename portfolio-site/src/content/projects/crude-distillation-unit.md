---
title: CrudeDistillationUnit
track: physical-ai
status: In Development
tagline: A NVIDIA Omniverse Kit + Isaac Sim digital twin of a generic Crude Distillation Unit with ISA-95 + Unified Namespace data structure designed for live OPC-UA binding and physics-based safety scenarios.
summary: A cloud-rendered industrial digital twin on the NVIDIA Physical AI stack — Omniverse Kit for the application shell, Isaac Sim for physics, USD for the scene graph. Five equipment pieces of a simplified CDU (furnace, column, two heat exchangers, pump) modeled as USD primitives in a 3-layer composition. Phase 0 (cloud GPU + Kit build + VNC streaming) complete; Phase 1 (scene authoring) in design. Planned phases layer a custom Kit extension, live OPC-UA binding, and Isaac Sim safety scenarios.
techStack:
  - NVIDIA Omniverse Kit 110.1.1
  - NVIDIA Isaac Sim (planned)
  - USD (Universal Scene Description)
  - Python 3.12
  - Vulkan
  - AWS EC2 g6.xlarge (NVIDIA L4 GPU)
  - Ubuntu 22.04
githubPath: 3.PhysicalAI/CrudeDistillationUnit
order: 0
---

<!-- DRAFT — pending Sowthri narrative -->

A digital twin of a Crude Distillation Unit, built on the NVIDIA Physical AI stack and rendered on a cloud GPU.

## What it is

A simplified CDU — the heart of any refinery — modeled in NVIDIA Omniverse Kit as a 3D scene with proper industrial data structure. Generic by design; not a model of any specific real refinery.

Five equipment pieces, each as a USD primitive (cylinder, box, or cone):

- **Furnace (F101)** — heats incoming crude to ~370 °C
- **Distillation Column (T101)** — separates crude into fractions
- **Heat Exchangers (E101, E102)** — recover heat from hot products
- **Pump (P101)** — moves crude through the system

The scene is authored in **3 USD layers** — geometry, materials, metadata — composed by a top-level scene file. Equipment paths follow **ISA-95** (`/RefinerySiteA/CDU_01/Column_T101`). A **Unified Namespace** (UNS) topic structure (`RefineryEnterprise/RefinerySiteA/CDU_01/Column_T101/top_pressure`) is defined for 21 parameters, with 10 prioritized for the live OPC-UA binding planned in Phase 3.

## Why NVIDIA Omniverse for this

Most refinery 3D models are CAD drawings — geometrically accurate, but disconnected from any operational data. The Omniverse stack flips that priority. The point isn't bolts and flanges; it's that the scene can be *bound to live process data*, simulate *physics-based safety scenarios* (gas dispersion, equipment failure, operator inspection), and ground *agentic reasoning* in a real spatial context. The same demo pattern that powers BMW's factory twin and Siemens' plant simulations, applied to an oil & gas use case.

Primitive geometry is deliberate. The portfolio piece demonstrates **USD composition, ISA-95 + UNS data structure, live data binding, and Isaac Sim physics** — the things that distinguish a digital twin from a 3D model. Photoreal CAD modeling is out of scope.

## Roadmap

| Phase | Status | What it produces |
| --- | --- | --- |
| Phase 0 — Cloud GPU + Kit foundation | ✅ done | AWS g6.xlarge with NVIDIA L4, Kit 110.1.1 application booting headless under Xvfb, browser-accessible VNC pipeline |
| Phase 1 — CDU scene | 🟡 design locked | Five equipment USD primitives, 3-layer USD composition, ISA-95 hierarchy, UNS metadata |
| Phase 2 — Custom Kit extension | ⏳ planned | `com.sowthri.cdutwin` extension with control panels for equipment parameters |
| Phase 3 — Live data binding | ⏳ planned | OPC-UA → Kit Fabric → scene attributes; 10 parameters streaming in real time |
| Phase 4 — Isaac Sim scenarios | ⏳ planned | Gas leak dispersion (Flow), rover inspection traverse, valve operation physics |
| Phase 5 — Polish, recording, snapshot | ⏳ planned | Demo recording, public artifacts, restorable infrastructure snapshot |

## Status

Early development. Phase 0 infrastructure is live but stopped between sessions to control cost. No public demo URL — the demo runs on an on-demand cloud GPU and is shared through screen recordings and the operator runbook, not a public endpoint. Source and full project documentation (charter, runbook, environment spec, Phase 1 design) available below.

[Source on GitHub →](https://github.com/sowthri-industrial-ai/AISolutionPortfolio/tree/main/3.PhysicalAI/CrudeDistillationUnit)

<!--
DRAFT — pending Sowthri narrative. The source material is technical
implementer docs (PROJECT_CHARTER.md, OPERATOR_RUNBOOK.md,
ENVIRONMENT_SPEC.md, PHASE1_DESIGN.md). Items I extrapolated for
portfolio-visitor framing — flag for refinement before final PR:

1. "Why NVIDIA Omniverse for this" — my framing connecting primitive
   geometry to the digital-twin pattern (BMW/Siemens references
   chosen as recognizable industrial-twin precedents). Verify or rewrite.

2. The roadmap table compresses 6 phases into a portfolio-visitor view;
   internal phase definitions in PROJECT_CHARTER.md §6 are richer.
   Order + status accurate as of design lock (2026-05-09).

3. No ARCHITECTURE.md exists yet (Phase 5b ADR-0002 four-point contract
   item #1). architectureDocPath frontmatter intentionally omitted
   until that artifact lands.

4. No screenshots in frontmatter — one VNC screenshot exists locally
   (Kit running on cloud GPU, "RTX Loading" overlay) but is
   gitignored. Decide before PR whether to host it in public/ or keep
   it operator-runbook-only.

5. Demo URL omitted by design — status="In Development", same pattern
   as refinery-digital-twin.md.
-->
