---
title: Refinery Digital Twin
track: assets-ai
status: In Development
tagline: A process-grade digital twin of a petroleum atmospheric distillation column with thermal-oil reboiler loop, designed to host an agentic-AI control layer.
summary: Builds a digital-twin foundation on DWSIM (open-source process simulator) with Python automation as the integration layer. Two coupled subsystems — petroleum side (Peng-Robinson EOS) and thermal-oil loop (CoolProp Incompressible). Currently in early development (Phase 0a — substrate inventory probe). Future phases layer Data Fabric, Twin orchestration, Agentic AI control, and an operator-facing Experience UI on top.
techStack:
  - DWSIM
  - Python 3.9
  - pythonnet
  - Mono x86_64
  - Peng-Robinson EOS
  - CoolProp (Incompressible Fluids)
  - Azure (planned)
githubPath: 2.AssetsAI/1.RefineryDigitalTwin
order: 0
---

<!-- DRAFT — needs Sowthri narrative -->

A digital-twin foundation for a petroleum refinery, with an agentic-AI control layer planned on top.

## What it is

The substrate is a locked DWSIM flowsheet — a 12-stage atmospheric distillation column with a thermal-oil reboiler heating loop. Two coupled property packages:

- **Petroleum side** (Peng-Robinson EOS) — multi-phase oil feed, light/intermediate/heavy product cuts, 30 pseudocomponents
- **Thermal-oil loop** (CoolProp Incompressible Fluids) — Therminol VP1 working fluid, heater + reboiler-proxy + pump + storage tank + recycle block

The flowsheet is a known-converged steady-state simulation. The work is building the data + control plane around it.

## Roadmap (per project briefing)

| Phase / Feature                      | Status         | What it produces                                                                                                                                                 |
| ------------------------------------ | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Phase 0a — Substrate inventory probe | 🟡 in progress | Canonical tag + setpoint dictionary covering every readable property and writable spec on the locked flowsheet — the data contract every later phase depends on. |
| Feature: Data Fabric                 | ⏳ planned     | Durable historian + tag schema                                                                                                                                   |
| Feature: Twin                        | ⏳ planned     | Runtime that mirrors the DWSIM substrate against live or synthetic data                                                                                          |
| Feature: Agentic AI                  | ⏳ planned     | Reuses the `framework/` package from HelloAgenticAI to put an agent loop in control of the twin                                                                  |
| Feature: Experience                  | ⏳ planned     | Operator-facing UI with the agent's reasoning visible — same "show every step" philosophy as HelloAgenticAI                                                      |

## Why this domain

Petroleum distillation is a real industrial process with non-trivial control coupling — composition shifts on the petroleum side change duty demand on the thermal-oil loop and vice versa. The digital twin is the testbed for an agent that has to reason about _both_ loops at once. The HelloAgenticAI framework provides the agent runtime; this project provides the domain.

## Status

Early development. No public demo URL. Source available below. Public-facing materials (architecture diagram, demo plan, screenshots) will land as later phases produce visible artefacts.

[Source on GitHub →](https://github.com/sowthri-industrial-ai/AISolutionPortfolio/tree/main/2.AssetsAI/1.RefineryDigitalTwin)

<!--
DRAFT — needs Sowthri narrative. The source briefing
(`2.AssetsAI/1.RefineryDigitalTwin/1.docs/phase0a_briefing.md`) is a
deep technical implementer doc — heavy on DWSIM API surface, light
on portfolio-visitor framing. Items I extrapolated from the briefing
but flag for refinement before PR opens:

1. The "What it is" section may compress the wrong things — the
   briefing focuses on the substrate-inventory probe as Phase 0a
   work; the broader project framing ("digital twin of a refinery
   with agentic AI on top") is mine.

2. The "Why this domain" section is my framing of the agentic-AI
   tie-in — the briefing doesn't explicitly say this is the testbed
   for HelloAgenticAI's framework. Verify or rewrite.

3. The Roadmap table compresses "Features Data Fabric, Twin,
   Agentic AI, Experience" mentioned in the briefing into a
   four-row table. Order + naming is per the briefing; the
   "what it produces" column is my synthesis.

4. No screenshots, no architecture diagram available yet — none
   referenced in frontmatter. Add when they exist.
-->
