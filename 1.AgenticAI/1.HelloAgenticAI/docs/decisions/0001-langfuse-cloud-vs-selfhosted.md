# 0001 — Langfuse Cloud (free tier) for v1, not self-hosted

## Status

Accepted, 2026-05-10.

## Context

`docs/ARCHITECTURE.md` §11 originally specified Langfuse as a **self-hosted sidecar Container App** for the live demo trace UI. `CLAUDE.md` §"Things to avoid" forbids introducing Postgres ("Cosmos is canonical"). Langfuse the application requires its own Postgres for trace storage.

These two constraints are in tension. We need to either:

- accept Postgres as an internal dependency of an observability tool (not application data), or
- pick a deployment model that avoids the conflict.

Additional constraints from the Phase 1 kickoff:

- Budget target: <$10/month idle, <$1/run
- Managed identity preferred everywhere; introducing a second secret store has cost
- Self-hosting Postgres adds operational surface (backups, upgrades, vault for the password, monitoring)
- Refinery and other vertical projects may have compliance posture that **requires** self-hosted observability (no SaaS allowed)

## Options considered

1. **Self-hosted Langfuse + Postgres sidecar Container App** — full Azure-native; adds Postgres dependency (conflicts with CLAUDE.md guidance) and operational toil
2. **Langfuse Cloud free tier** — managed SaaS; zero infra to maintain; two API keys to store; SaaS dependency outside Azure
3. **Skip Langfuse, App Insights only** — loses the polished trace UI that makes the live demo land for non-technical reviewers

## Decision

Use **Langfuse Cloud free tier** (https://cloud.langfuse.com) for HelloAgenticAI v1.

The two API keys (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) are stored in Key Vault — they are the only non-Azure secrets in the project. The Container App's user-assigned managed identity reads them at startup via Key Vault references; they never appear in source, env vars at rest, or in CI variables.

## Consequences

Positive:

- No self-hosted Postgres, no sidecar, no operational toil
- Free tier covers v1 traffic (50K observations/month) comfortably
- The polished Langfuse trace UI is still available for the live demo
- Faster Phase 4 implementation: SDK calls only, no infra wiring
- Cleaner v1 ARCHITECTURE diagram

Negative (and mitigations):

- Langfuse Cloud is a SaaS dependency outside Azure — *mitigation:* App Insights remains the production-grade trace store; Langfuse is the demo polish layer. If Langfuse Cloud is unavailable, the agent still works; only the demo UI degrades.
- Refinery verticals with compliance constraints may need self-hosted Langfuse — *mitigation:* `framework/observability/` ships with `AgentEventEmitter` accepting pluggable sinks; swapping in a self-hosted Langfuse sink is a constructor-argument change, not a refactor. Self-hosting remains the documented upgrade path in `docs/ARCHITECTURE.md` §11.

## Scope

This decision applies to **HelloAgenticAI v1 only**. Refinery and other vertical projects re-evaluate based on their compliance posture. The framework's observability layer is provider-agnostic and does not depend on Langfuse Cloud specifically.

## References

- `docs/ARCHITECTURE.md` §11 Observability
- `CLAUDE.md` §"Things to avoid" — no Postgres
- `PROJECT_PLAN.md` Phase 4 — observability and guardrails wired live
- Langfuse Cloud: https://cloud.langfuse.com
- Langfuse self-hosting docs (upgrade path for compliance-constrained verticals): https://langfuse.com/docs/deployment/self-host
