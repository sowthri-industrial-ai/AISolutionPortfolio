# ADR-0004 — Agentic AI via custom MCP server, not a framework

**Status:** Accepted
**Date:** 2026-05-02
**Deciders:** Architect

## Context

The platform needs four AI agents (Reliability, Operations, Energy, Safety) that:

- Reason over live twin state, historian data, alerts, and SOPs
- Take bounded actions through well-defined tools
- Are auditable and explainable
- Are differentiating in interview

MCP is the emerging standard for tool-use in production agentic systems, with growing adoption across enterprise platforms. The wider market also offers LangChain/LangGraph, AutoGPT-style agent loops, and Azure OpenAI's native function-calling.

## Decision

We will implement a **custom Model Context Protocol (MCP) server** that exposes the platform's capabilities as MCP tools, with **Anthropic Claude** as the LLM, and four agent profiles each with a tool allow-list. No agent framework (LangChain, LangGraph, etc.) is used.

## Alternatives considered

### Option A — Custom MCP server with Claude (chosen)

- **Pros:** MCP is the open standard for tool-using LLMs. Differentiates the candidate (most portfolios don't have it). Aligns with the JD's Gen AI Architect framing. Direct Anthropic SDK; no framework drag.
- **Cons:** Requires writing the MCP server. Slightly more boilerplate than LangChain's `@tool` decorator.
- **Why chosen:** Differentiation + alignment + cleanliness.

### Option B — LangChain / LangGraph

- **Pros:** Familiar to many developers. Many built-in integrations.
- **Cons:** Heavy abstraction tax. Frequent breaking changes. Tools tied to framework. Hard to demonstrate "I understand what's happening" in interview.
- **Why not chosen:** Framework lock-in for four agents is overkill.

### Option C — Azure OpenAI native function-calling

- **Pros:** Tight Azure integration. Single LLM provider.
- **Cons:** Locks tools to OpenAI. No standard protocol. Less interesting story.
- **Why not chosen:** MCP is the future-proof, model-agnostic choice.

### Option D — Multi-agent framework (CrewAI, AutoGen)

- **Pros:** Built-in multi-agent orchestration patterns.
- **Cons:** For four agents with clear tool boundaries and no inter-agent collaboration in scope, this is over-engineering.
- **Why not chosen:** YAGNI.

## Consequences

### Positive

- Single, well-typed MCP server is easy to demo: "let me show you the tools."
- Tools work with any MCP-compatible client (Claude Desktop, Cursor, custom UIs).
- Per-agent allow-lists enforce least-privilege at the tool layer.
- Future agents reuse the same tools without re-implementing them.

### Negative

- More upfront code than `@tool`-decorating Python functions.
- MCP tooling ecosystem is younger; some integration gaps to fill manually.
- Agents do not collaborate (e.g., reliability agent can't call energy agent). If we later need multi-agent collaboration, that's an ADR.

### Neutral

- Each agent is a Python class with: name, description, system prompt, tool allow-list, conversation memory limit.

## MCP tools (initial set)

These are the tools the MCP server exposes. Per-agent allow-lists in `ai-agents/agents/<agent>.py`.

| Tool | Description | Used by |
|---|---|---|
| `get_asset_state(asset_id)` | Live state from ontology + last telemetry | All |
| `query_historian(tag, from, to, agg)` | Time-series query | Reliability, Ops, Energy |
| `list_active_alerts(unit_id, severity)` | Current alerts | Ops |
| `predict_failure(asset_id, horizon_h)` | Calls anomaly service for RUL | Reliability |
| `run_what_if(scenario_id, params)` | Executes simulation | Energy |
| `get_sop(equipment_class, situation)` | RAG over SOP corpus | Ops, Safety |
| `get_p_and_id_excerpt(unit_id, asset_id)` | RAG over P&ID descriptions | Safety |
| `get_failure_modes(equipment_class)` | ISO 14224 failure modes | Reliability, Safety |

## Per-agent tool allow-lists

```yaml
reliability:
  tools: [get_asset_state, query_historian, predict_failure, get_failure_modes]
operations:
  tools: [get_asset_state, query_historian, list_active_alerts, get_sop]
energy:
  tools: [get_asset_state, query_historian, run_what_if]
safety:
  tools: [get_asset_state, get_sop, get_p_and_id_excerpt, get_failure_modes]
```

The Safety agent is intentionally read-only and cannot run simulations.

## Compliance / cross-cutting

- **Auditability:** Every tool call is logged with agent identity, parameters, and result digest.
- **Security:** Allow-lists enforced server-side. Tool calls outside allow-list are rejected.
- **Reproducibility:** Conversation transcripts stored in OneLake for review.

## Validation

- Each agent answers a representative question correctly using only its allow-listed tools (Story AI-001..004)
- Tool call latency p95 < 500ms (excluding LLM time)
- Audit log captures every tool call

## Open follow-ups

- Multi-agent collaboration patterns (deferred until there's a use case)
- Agent evaluation framework (do we need automated eval beyond manual review?) — ADR if needed
