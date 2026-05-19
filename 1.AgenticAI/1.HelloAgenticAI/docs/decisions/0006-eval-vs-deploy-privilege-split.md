# 0006 — Split eval data-plane access from deploy privilege

## Status

Accepted, 2026-05-19.

## Context

Phase 5c was framed as two coupled deliverables: (1) grant the GitHub-federated SP `Contributor` + `User Access Administrator` on `rg-helloagenticai-dev`, and (2) wire the `EvalHarness` into CI. Pre-flight reading showed the coupling is wrong:

- `framework/eval/harness.py` — `EvalHarness.run_case` calls `await self._agent.run(...)` (the real fruit-market agent) and `LLM_JUDGE` needs a live `AzureOpenAIClient`. Evals need Azure **data-plane invoke** (AOAI, Cosmos, Content Safety, Key Vault) — not control-plane.
- `docs/setup-oidc.md` "Phase 5c+" — its `Contributor`+`UAA` block is justified for **`azd up`** ("*UAA is required because infra/main.bicep creates role assignments for the runtime MI*"), i.e. the **deploy** path. It explicitly defers the eval data-plane needs to `docs/decisions/TODO-phase-5-data-plane-rbac.md`.
- `TODO-phase-5-data-plane-rbac.md` — the OIDC SP's eval needs are **5 data-plane roles** ("for evals workflow"), distinct from `Contributor`/`UAA`.

No `deploy.yml` exists (only `oidc-verify.yml` at repo root). `Contributor`+`UAA` would therefore be the project's single highest-consequence grant with **no consumer**. This contradicts CLAUDE.md's least-privilege convention and ADR-0005's deferral discipline. ADR-0003 risk #12 further requires that a privileged workflow be trust-verified by a **non-privileged path** before it reaches the default branch.

## Options considered

1. **Bundle** — one credential carrying `Contributor`+`UAA`+data-plane for "all of CI." Rejected: conflates deploy and eval, attaches catastrophic privilege with no consumer, maximal standing blast radius.
2. **Grant `Contributor`+`UAA` now "to be ready"** — rejected: YAGNI; standing highest-consequence privilege with no `deploy.yml` to use it; violates least privilege.
3. **Split** — eval CI gets ONLY the 5 RG-scoped data-plane roles via a new environment-scoped credential; `Contributor`+`UAA` explicitly deferred to a future deploy phase. Chosen.

## Decision

**Eval CI and deploy privilege are separate concerns with separate credentials.**

Eval path (Phase 5c, authorized):

- New federated-credential subject `repo:sowthri-industrial-ai/AISolutionPortfolio:environment:evals` (new; never reuse `oidc-verify`'s, never repo-wide/`pull_request`).
- New GitHub Environment `evals` with its own required-reviewer gate (reviewer = Sowthri), `prevent_self_review: false`, no branch policy.
- The 5 RG-scoped data-plane roles on the SP (`4bc75532-91d1-4b68-8a60-019e6611bce0`), scope `/subscriptions/d599c6a3-6859-4aae-8c0e-63674a3b0704/resourceGroups/rg-helloagenticai-dev`:

  | Service | Role | Role-def GUID | Mechanism |
  |---|---|---|---|
  | Azure OpenAI | Cognitive Services OpenAI User | `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd` | `az role assignment create` (standard RBAC, RG scope) |
  | Content Safety | Cognitive Services User | `a97b65f3-24c7-4388-baec-2e87135dc908` | same |
  | Storage | Storage Blob Data Contributor | `ba92f5b4-2d11-453d-a403-e96b0029c9fe` | same |
  | Key Vault | Key Vault Secrets User | `4633458b-17de-408a-b874-0445c86b69e6` | same |
  | Cosmos DB | Cosmos DB Built-in Data Contributor | `00000000-0000-0000-0000-000000000002` | **Cosmos-native** — `az cosmosdb sql role assignment create` (NOT `az role assignment create`); account-scoped |

Staged per ADR-0003 risk #12: create the zero-role credential + environment → an inert `evals-trust-verify.yml` (the proven 5b pattern, bound to `environment: evals`) proves the new subject **with zero privilege** → only then attach the 5 data-plane roles (isolated, hard-gated) → only then the privileged `evals.yml`. `azure/login` is SHA-pinned to `a457da9ea143d694b1b9c7c869ebb04ebe844ef5` (v2.3.0) identically across `oidc-verify.yml`, `evals-trust-verify.yml`, and (later) `evals.yml`.

### Deferred: Contributor + User Access Administrator (a decision, not an oversight)

`Contributor` + `User Access Administrator` on `rg-helloagenticai-dev` is **deliberately deferred as of 2026-05-19** and is **out of Phase 5c**. It is not granted, not staged, not pre-created.

- **Reason:** (a) no consumer — there is no `deploy.yml`; nothing uses it. (b) Highest blast radius in the project: `UAA` on the live-data RG = a compromised federated identity can grant itself or any principal **any role on every resource in `rg-helloagenticai-dev`** (Cosmos data, Key Vault secrets incl. Langfuse keys, AOAI, the agent Container App); `Contributor` = create/modify/**delete** every resource in it. Effectively total compromise of the live-data RG.
- **Condition to grant later:** a real `deploy.yml` exists and demonstrably requires it — granted then in **its own phase**, with **its own hard gate**, **its own ADR justification**, and its own environment-scoped credential (e.g. `environment:deploy`), never reusing the eval credential.
- **Future reader:** this deferral was an evidence-based decision (3 sources, above), not a forgotten task. If you are here because a `deploy.yml` now needs it, open a new ADR; do not retrofit it onto the eval credential.

### Follow-up: azure/login Node-20 → Node-24

Tracked here (not `framework-v2-backlog.md`, which is scoped to `framework/` package structural gaps — a third-party-action runtime deprecation does not fit that doc's charter or per-entry format). `oidc-verify.yml`, `evals-trust-verify.yml`, and (later) `evals.yml` pin `azure/login@a457da9ea143d694b1b9c7c869ebb04ebe844ef5` (v2.3.0), which runs on **Node.js 20**. GitHub Actions deprecation: forced to Node 24 on **2026-06-02**, Node 20 removed **2026-09-16**. **Action:** when `azure/login` ships a Node-24 release, bump the pinned SHA across every workflow using it and re-verify via the trust-verify workflow(s). Owner: the next workflow-touching phase. (5c lands well before 2026-06-02; not a blocker.)

## Consequences

Positive:

- Least privilege: the eval credential can read/invoke data-plane on one RG and nothing more — no resource create/delete, no privilege escalation, no role grants.
- The project's catastrophic privilege (`Contributor`+`UAA`) never exists until a workflow actually needs it; smallest possible standing blast radius.
- Trust is verified non-privileged first (risk #12): a new-subject typo is caught at the inert `evals-trust-verify` step with zero privilege exposed.

Negative (and mitigations):

- When `deploy.yml` eventually lands it needs its own privilege phase. *Mitigation:* that is the intended design; recorded above so it is a decision, not a surprise.
- Data-plane RBAC propagation lag — ADR-0003 risk #7: AOAI / Content Safety grants can take 15–45 min to propagate, so the first `evals.yml` run may 401/403 even though trust is fine. *Mitigation:* named failure mode; the non-privileged trust proof isolates "trust works" from "roles propagated"; wait-and-retry, do not misdiagnose as a trust failure.
- Cosmos uses a separate RBAC system (`Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments`) with different tooling and propagation. *Mitigation:* explicit separate command (`az cosmosdb sql role assignment create`), flagged at the privilege-grant batch.

### Post-5c security boundary: shared-principal privilege coupling

The eval credential and the 5b `oidc-verify` credential authenticate as the **same service principal** (`4bc75532-91d1-4b68-8a60-019e6611bce0`, app `e6422971-a9f7-4d66-89f2-9d1d9c431e94`) — deliberately one app with two federated credentials. **After Batch 4 attaches the 5 data-plane roles, that shared SP is privileged.** Consequence: `oidc-verify.yml`'s "zero RBAC" property becomes a statement about the **workflow** (it exercises no RBAC) and **no longer** about the **principal** (which now holds data-plane roles on `rg-helloagenticai-dev`).

From Batch 4 onward the privileged eval path's **only** security boundary is the `evals` GitHub Environment's required-reviewer gate **plus** the environment-scoped subject. There is no "the SP has no permissions" backstop anymore (unlike pre-5c): a mis-scoped or typo'd `evals` subject, or a compromised / incautious reviewer approval, is the **entire** exposure — it directly yields the SP's data-plane access to `rg-helloagenticai-dev`.

*Mitigation:* this is precisely why the `evals` subject is environment-scoped (never repo-wide / `pull_request`) and the `evals` environment enforces a required reviewer — these two controls are now **load-bearing**, not defence-in-depth. It is also why `Contributor`/`UAA` stays deferred: it keeps the shared SP's worst-case blast radius at **data-plane-on-one-RG**, not total-RG-compromise, so a boundary failure is serious-but-bounded rather than catastrophic.

*Future reader:* a single-app / two-credential design was chosen over two separate app registrations for operational simplicity (one app to rotate, one `az ad app delete` to revoke everything). The accepted, deliberate cost is this shared-principal privilege coupling — `oidc-verify`'s principal is privileged post-5c even though that workflow itself uses none of it. The coupling is bounded **by choice** via the deferred `Contributor`/`UAA`; do not "tidy up" by adding broader roles to this shared SP without re-evaluating this boundary.

## Scope

Applies to HelloAgenticAI CI for Phase 5c onward: the eval federated credential, the `evals` environment, and the 5 data-plane roles on SP `4bc75532-91d1-4b68-8a60-019e6611bce0` in `rg-helloagenticai-dev`. Explicitly **out of scope:** the deploy privilege (`Contributor`+`UAA`), deferred above. Identity/federated-credential/RBAC operations are executed by Sowthri from proposed scripts; Claude proposes and never runs them (CLAUDE.md workflow rule 4). Vertical projects (RefineryDigitalTwin, etc.) re-evaluate per project — own app registration, own RG-scoped grants, own split.

## References

- `docs/decisions/0005-oidc-federated-credential-trust-model.md` — the OIDC trust model + privilege-deferral discipline this builds on
- `docs/decisions/0003-azd-up-preflight-risks.md` — risk #12 (non-privileged verification path) + risk #7 (data-plane RBAC propagation lag)
- `docs/setup-oidc.md` — the runbook; its "Phase 5c" (eval data-plane, authorized) vs "Deploy privilege" (deferred) split implements this ADR
- `docs/decisions/TODO-phase-5-data-plane-rbac.md` — the per-service data-plane grant matrix (`oidcServicePrincipalId`)
- `framework/eval/harness.py` — why evals need data-plane (runs the real agent)
- `PROJECT_PLAN.md` Phase 5 — evals.yml acceptance criteria
- `CLAUDE.md` — workflow rule 4 (approval gates), least-privilege convention
