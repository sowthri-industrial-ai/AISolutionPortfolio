---
title: Refinery Digital Twin
tagline: Azure-native digital twin for petroleum distillation, grounded in DWSIM steady-state simulation and ISA-95 ontology.
status: "Phase 1 foundation complete; Stages 2-6 and Features 1, 2, 3, 5 in progress"
github_url: https://github.com/sowthri-industrial-ai/AISolutionPortfolio/tree/main/2.AssetsAI/1.RefineryDigitalTwin
demo_url: ""  # populated by `azd env get-values | grep DEMO_URL` after `azd up`
tech_stack:
  - DWSIM 9.0.5 (Mono x86_64)
  - Python 3.9.6
  - pythonnet 3.0.5
  - Microsoft Fabric (Eventstream + Eventhouse + OneLake)
  - Fabric IQ Digital Twin Builder
  - DTDL
  - ISA-95
  - Foundry agents
  - Azure OpenAI (gpt-4o, gpt-4o-mini)
  - Azure AI Search
  - MCP servers
  - Real-Time Dashboard (KQL)
  - Power BI
  - NVIDIA Omniverse
  - Azure Static Web Apps
  - Bicep + azd
  - GitHub Actions (OIDC)
screenshots: []  # populated as features land — placeholder for now
---

# Refinery Digital Twin

A Phase 1 foundation has shipped: the locked DWSIM 9.0.5 sample `Petroleum Distillation with Reboiler Heating Fluid.dwxmz` runs on macOS Mono x86_64, a Python streamer solves it every 30 seconds and emits 1550-tag JSON snapshots, and a placeholder Static Web App carries the portfolio profile until Feature 5's full UI lands. Above it: Microsoft Fabric ingests the snapshot stream into an Eventhouse and OneLake; an ISA-95 + DTDL twin ontology indexes the live state in Fabric IQ; Foundry agents (inheriting HelloAgenticAI's framework) reason over the twin with MCP-served tools and AI Search RAG; and a Real-Time Dashboard, Power BI, and Omniverse 3D scene render the operator experience. The substrate is small, the layers above are full Azure-native — credentials demo for an industrial AI engineer.

## Status by feature

- **F4 · Simulation substrate** ✅ Phase 0a inventory + Stage 1 streamer (1550 tags, 30 s cycle)
- **F5 · Experience layer** 🔄 Phase 1 placeholder shipping; full UI in a later phase
- **F1 · Data Fabric** ⬜ planned (Eventstream → Eventhouse → OneLake)
- **F2 · Twin ontology** ⬜ planned (Fabric IQ + DTDL + ISA-95)
- **F3 · Agentic AI** ⬜ planned (Foundry agents + Azure OpenAI + MCP + AI Search)

## Links

- Architecture: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)
- Source: [github.com/sowthri-industrial-ai/AISolutionPortfolio](https://github.com/sowthri-industrial-ai/AISolutionPortfolio/tree/main/2.AssetsAI/1.RefineryDigitalTwin)
- Foundation framework: [HelloAgenticAI](https://github.com/sowthri-industrial-ai/AISolutionPortfolio/tree/main/1.AgenticAI/1.HelloAgenticAI)

<!--
Schema status: CANDIDATE CANONICAL.
This file authors the portfolio's project-metadata schema ahead of
HelloAgenticAI Phase 5's own metadata file, which has not been
written. The portfolio site will read YAML frontmatter (title,
tagline, status, github_url, demo_url, tech_stack[], screenshots[])
plus the markdown body as a project overview, per Astro content
collection conventions referenced in HelloAgenticAI ADR-0002. When
HelloAgenticAI Phase 5 lands its own metadata file, the portfolio
coordinator decides which schema is canonical and the other mirrors.
-->
