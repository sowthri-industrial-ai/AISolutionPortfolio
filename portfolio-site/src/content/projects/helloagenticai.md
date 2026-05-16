---
title: HelloAgenticAI
track: agentic-ai
status: Live
tagline: A live agentic AI demo — the agent plans, calls tools, reflects, and replans against six mock fruit shops, with every step streamed to the browser.
summary: Production-grade Azure-native runtime for plan / route / reflect / terminate agent loops, demonstrated with a fruit-market shopping agent. Every chat session shows the agent's reasoning live, produces a queryable Langfuse trace, and ships events to an App Insights workbook. Built in five phases — framework + infra, demo, observability + guardrails, portfolio publishing.
techStack:
  - Python 3.12
  - LangGraph
  - Chainlit
  - Azure OpenAI (gpt-4o + gpt-4o-mini)
  - Azure Container Apps
  - Cosmos DB
  - Azure AI Content Safety
  - App Insights
  - Langfuse Cloud
  - Bicep + azd
githubPath: 1.AgenticAI/1.HelloAgenticAI
demoUrl: https://ca-agent-dev-zld3sf6mfagdq.agreeableground-e8c6d28f.swedencentral.azurecontainerapps.io/
architectureDocPath: 1.AgenticAI/1.HelloAgenticAI/docs/ARCHITECTURE.md
order: 0
---

<!-- DRAFT — pending Sowthri review -->

A working agentic-AI demo, end-to-end, with all the production scaffolding visible.

## What it does

You type a fruit-shopping request — _"Buy a tropical fruit basket under $20 — include pineapple, mango, and dragon fruit"_ — and the agent plans the basket, picks shops, calls them, reflects on what it got, and replans when something is unavailable. Every step renders in the UI as it happens: planning, tool calls with arguments, tool results, reflection verdicts, the final basket.

Six mock fruit shops back the demo, each with deliberately varied inventory to exercise different agent paths: happy-path single-shop, replan, rationing, partial fulfillment, terminal failure handled gracefully.

## Why a fruit market

The domain is intentionally trivial — universally relatable, no domain knowledge required to read the trace. What stands out is the _machinery_: planner / router / reflector / terminator nodes (LangGraph), Pydantic-validated structured outputs, Content Safety input + output gates, real-time Langfuse trace tree, App Insights workbook with five live KQL charts. Every layer is visible in code and observable at runtime.

The framework that powers it (the `framework/` package — agents, guardrails, observability, memory, tools, LLM client) is reusable. Subsequent vertical projects (refinery, etc.) inherit it and swap only the demo layer.

## What Phase 4 added

The Phase 3 demo loop runs unchanged. Phase 4 wraps it with four production-grade signals:

- **Real-time Langfuse trace tree** per chat session — clickable link below each agent answer, showing `agent_run` → `plan` → `tool:<shop>` → `reflect` as nested spans.
- **App Insights workbook** with five live KQL charts: agent runs, events per minute by type, p50/p95 plan-to-complete latency, top schema-validation failures, top Content Safety blocks. Cost-trend chart deferred to v2.
- **Content Safety gates** on input _and_ output. End-to-end verified: a Microsoft-documented Violence Level 4 prompt fires `GUARDRAIL_BLOCKED(gate="input")` → friendly UI refusal → workbook row.
- **Pydantic schema validation with retry** on every LLM call and tool I/O boundary — 3 attempts, each retry emitting `SCHEMA_VALIDATION_FAILED`, the third propagating as a typed exception.

All four follow the same fail-open lazy-init contract: construct cheap, init on first use, never crash the agent on observability misconfiguration.

## Phases at a glance

| Phase                          | Status         | What landed                                                                                                                  |
| ------------------------------ | -------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 1 — Infrastructure             | ✅             | Bicep stack: Container Apps, AOAI, Cosmos, Content Safety, Key Vault, App Insights, Langfuse plumbing, ACR, managed identity |
| 2 — Framework                  | ✅             | `framework/` package — agents, guardrails, llm, memory, observability, tools                                                 |
| 3 — Demo                       | ✅             | Six fruit shops, FruitMarketAgent, Chainlit UI streaming every step                                                          |
| 4 — Observability + guardrails | ✅             | Langfuse, App Insights workbook, Content Safety gates, schema-validation retry                                               |
| 5 — Portfolio + evals + CI     | 🟡 in progress | This site (5a), evals harness, OIDC GitHub Actions, on-demand provisioning                                                   |

## Decisions worth a read

- [ADR-0001](https://github.com/sowthri-industrial-ai/AISolutionPortfolio/blob/main/1.AgenticAI/1.HelloAgenticAI/docs/decisions/0001-langfuse-cloud-vs-selfhosted.md) — Langfuse Cloud over self-hosted for v1
- [ADR-0002](https://github.com/sowthri-industrial-ai/AISolutionPortfolio/blob/main/1.AgenticAI/1.HelloAgenticAI/docs/decisions/0002-portfolio-site-stack-astro.md) — Astro + Tailwind + Static Web Apps (this site)
- [ADR-0003](https://github.com/sowthri-industrial-ai/AISolutionPortfolio/blob/main/1.AgenticAI/1.HelloAgenticAI/docs/decisions/0003-azd-up-preflight-risks.md) — `azd up` preflight risks (9 risks documented as they were learned the hard way)

## Try it

The deployed demo URL above is the live Phase 4 build. The "Run live demo on-demand" button (Phase 5d, coming) will provision a fresh environment per visitor and tear it down after; until then, the always-on URL is shared.

[Source on GitHub →](https://github.com/sowthri-industrial-ai/AISolutionPortfolio/tree/main/1.AgenticAI/1.HelloAgenticAI)

<!-- DRAFT — pending Sowthri review: tone, framing, what to emphasise to a portfolio visitor (vs. the developer-facing README in the repo). Replace markers with finalised copy before PR opens. -->
